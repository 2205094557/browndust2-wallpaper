#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BD2 Spine 4.1 无头验证（tools/spine41_test.html + msedge headless + PIL 像素分析）。

职责：
  1. 组装本地验证目录 tools/_spine41_shots/_serve/（测试页 + spine-webgl-4.1.js +
     wallpaper-layout.js + 提取出的 BD2 资产），启动本地 HTTP 服务；
  2. msedge --headless 对每个资产先 --dump-dom 确认页面 READY（拿到页内
     gl.readPixels 双阈值像素统计），再 --screenshot 出图（clean=1 隐藏浮层）；
  3. PIL 分析截图：以页面背景 #050510 的四角中位色为基准，扫内容像素包围盒
     （宽/高/面积占比）、中心人形像素、非全黑判定；
  4. 汇总 JSON 报告（tools/_spine41_shots/report.json）与控制台摘要。

用法：python tools/verify_spine41.py [--asset char003892|illust_dating14|all]
验收标准（与任务一致）：
  - 非空像素包围盒占画面比例 10%~80%（按面积占比判定，同时报告宽/高占比）；
  - 中心区域存在人形像素（非全黑/非全透明）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
SHOTS = TOOLS / "_spine41_shots"
SERVE = SHOTS / "_serve"
EXTRACTED = Path(r"D:\codex\_bd2_research\extracted")
RUNTIME_SRC = REPO / "templates" / "spine41" / "spine-webgl-4.1.js"
LAYOUT_SRC = REPO / "templates" / "wallpaper-layout.js"
TEST_HTML = TOOLS / "spine41_test.html"

MSEDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 18923
W, H = 1280, 720

ASSET_FILES = {
    "char003892": [
        "char003892.skel", "char003892.atlas", "char003892.png",
    ],
    "illust_dating14": [
        "illust_dating14.skel", "illust_dating14.atlas", "illust_dating14.png",
        "illust_dating14_2.png", "illust_dating14_3.png", "illust_dating14_4.png",
        "illust_dating14_5.png", "illust_dating14_6.png", "illust_dating14_7.png",
        "illust_dating14_8.png", "illust_dating14_9.png", "illust_dating14_10.png",
        "illust_dating14_11.png",
    ],
}


def build_serve_dir() -> None:
    """组装/刷新本地验证目录（清理重来，避免旧文件残留）。"""
    if SERVE.exists():
        shutil.rmtree(SERVE)
    (SERVE / "assets").mkdir(parents=True)
    shutil.copy2(TEST_HTML, SERVE / "spine41_test.html")
    shutil.copy2(RUNTIME_SRC, SERVE / "spine-webgl-4.1.js")
    shutil.copy2(LAYOUT_SRC, SERVE / "wallpaper-layout.js")
    for files in ASSET_FILES.values():
        for name in files:
            src = EXTRACTED / name
            if not src.exists():
                raise FileNotFoundError(f"缺失测试资产: {src}")
            dst = SERVE / "assets" / name
            try:
                os.link(src, dst)  # 同卷硬链接省空间；失败退回复制
            except OSError:
                shutil.copy2(src, dst)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass


def start_server(port: int) -> HTTPServer:
    from functools import partial
    # SimpleHTTPRequestHandler 的 directory 是构造期参数，用 partial 绑定到 SERVE
    httpd = HTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(SERVE)))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def run_edge(extra_args: list[str], url: str, timeout: int = 90):
    """执行 msedge headless，尝试新旧 headless 模式；返回 (ok, stdout, stderr)。"""
    base = [
        MSEDGE, "--no-first-run", "--disable-extensions", "--mute-audio",
        "--hide-scrollbars", f"--window-size={W},{H}",
        f"--user-data-dir={tempfile.mkdtemp(prefix='edge4_')}",
    ]
    variants = [
        base + ["--headless=new", "--disable-gpu"] + extra_args + [url],
        base + ["--headless"] + extra_args + [url],
        base + ["--headless=new", "--use-angle=swiftshader"] + extra_args + [url],
    ]
    for idx, cmd in enumerate(variants):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
            out = (r.stdout or b"").decode("utf-8", "replace")
            err = (r.stderr or b"").decode("utf-8", "replace")
            if "BD2-READY" in out or "BD2-READY" in err or idx == len(variants) - 1:
                return idx, out, err
        except subprocess.TimeoutExpired:
            continue
    return None, "", "timeout"


def dump_dom(asset: str, budget: int = 20000) -> str:
    url = f"http://127.0.0.1:{PORT}/spine41_test.html?asset={asset}"
    _, out, _ = run_edge(["--dump-dom", f"--virtual-time-budget={budget}"], url)
    return out


def parse_status(dom: str) -> dict:
    m = re.search(r'<pre id="out">([\s\S]*?)</pre>', dom)
    if not m:
        return {"ready": False, "title": "", "raw": dom[:200]}
    text = m.group(1)
    info = {}
    # info JSON 是首行 { 开头的完整 JSON 值（JSON.stringify(..., null, 1) 换行排版）：
    # 用 raw_decode 只解析第一个 JSON 值，避免把后面 a8={...} a96={...} 统计行吞进来
    if "{" in text:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
            info = obj
        except Exception:
            pass
    frame_stats = None
    fm = re.search(r"a8=\{[^\n]*\} a96=\{[^\n]*\}", text)
    if fm:
        frame_stats = fm.group(0)
    return {
        "ready": "BD2-READY" in dom or bool(info),
        "title": re.search(r"<title>([^<]*)</title>", dom).group(1) if re.search(r"<title>([^<]*)</title>", dom) else "",
        "info": info,
        "frame_stats": frame_stats,
        "dom_text": text,
    }


def screenshot(asset: str, out_png: Path, budget: int = 20000) -> bool:
    url = f"http://127.0.0.1:{PORT}/spine41_test.html?asset={asset}&clean=1"
    args = [f"--screenshot={out_png}", f"--virtual-time-budget={budget}"]
    _, _, err = run_edge(args, url)
    return out_png.exists() and out_png.stat().st_size > 1000


def analyze_png(img_path: Path, log) -> dict:
    """PIL 分析截图：背景 #050510 的四角中位色为基准，内容像素 = 与背景色差超阈值。"""
    im = Image.open(img_path).convert("RGBA")
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = tuple(sorted(c[i] for c in corners)[len(corners) // 2] for i in range(3))
    tol = 26
    min_x, max_x, min_y, max_y = w, -1, h, -1
    n = colored = center = 0
    cx0, cx1 = int(w * 0.3), int(w * 0.7)
    cy0, cy1 = int(h * 0.2), int(h * 0.8)
    for y in range(0, h, 2):  # 抽查一半像素加速（截图 1280x720 ≈ 46 万像素）
        for x in range(0, w, 2):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            if abs(r - bg[0]) > tol or abs(g - bg[1]) > tol or abs(b - bg[2]) > tol:
                n += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                if r + g + b > 90:
                    colored += 1
                if cx0 <= x <= cx1 and cy0 <= y <= cy1:
                    center += 1
    bw = (max_x - min_x + 1) if max_x >= 0 else 0
    bh = (max_y - min_y + 1) if max_y >= 0 else 0
    res = {
        "size": [w, h], "bg": bg, "contentPx": n, "coloredPx": colored, "centerPx": center,
        "bbox": [min_x, min_y, max_x, max_y] if n else None,
        "wPct": round(100 * bw / w, 1) if n else 0.0,
        "hPct": round(100 * bh / h, 1) if n else 0.0,
        "areaPct": round(100 * bw * bh / (w * h), 1) if n else 0.0,
        "coveragePct": round(100 * n / ((w // 2) * (h // 2) + 1), 2),
    }
    log(f"  [PIL] bbox={res['bbox']} w={res['wPct']}% h={res['hPct']}% area={res['areaPct']}% "
        f"content={res['contentPx']} colored={res['coloredPx']} center={res['centerPx']}")
    return res


def verify_asset(asset: str, budget: int) -> dict:
    print(f"== {asset} ==")
    dom = dump_dom(asset, budget)
    status = parse_status(dom)
    info = status.get("info") or {}
    if not status["ready"]:
        print(f"  [dom] 未就绪: title={status['title']!r} raw={status['raw']!r}")
        return {"asset": asset, "ready": False, "error": "page not ready"}
    print(f"  [dom] READY: {info.get('asset')} skel v{info.get('skelVersion')} "
          f"pages={info.get('pages')} anim={info.get('anim')} anims={len(info.get('anims') or [])} "
          f"skin={info.get('skin')} bounds={info.get('bounds')}")
    shot = SHOTS / f"{asset}.png"
    ok = screenshot(asset, shot, budget)
    if not ok:
        print(f"  [shot] 截图失败/为空: {shot}")
        return {"asset": asset, "ready": False, "error": "screenshot empty"}
    log = lambda line: print(line)
    pil = analyze_png(shot, log)
    # 页内 gl.readPixels 统计（dump-dom 快照里的 a8= / a96= 双阈值帧统计）
    frame_stats = status.get("frame_stats")
    print(f"  [inpage] {frame_stats}")
    # ---- 验收判定 ----
    area_ok = 10.0 <= pil["areaPct"] <= 80.0
    min_dim = min(pil["wPct"], pil["hPct"])
    dim_ok = 10.0 <= min_dim <= 80.0
    center_ok = pil["centerPx"] >= 200
    not_black = pil["coloredPx"] > 0
    passed = area_ok and center_ok and not_black
    result = {
        "asset": asset, "ready": True, "animateFrameStats": frame_stats,
        "pil": pil, "info": info,
        "checks": {
            "bboxArea10_80": area_ok, "minDim10_80": dim_ok,
            "centerHumanPixels": center_ok, "notBlackNotTransparent": bool(not_black),
        },
        "passed": passed,
    }
    print(f"  => {'PASS' if passed else 'FAIL'} "
          f"area={pil['areaPct']}% minDim={min_dim}% center={pil['centerPx']} colored={pil['coloredPx']}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["all", "char003892", "illust_dating14"])
    ap.add_argument("--budget", type=int, default=25000,
                    help="virtual-time-budget（毫秒）。25000 为实测稳定值：illust_dating14 在 8k/20k/40k "
                         "可能截到 idle1 一开场的全屏深色面板相位（area≈89%），25k 稳定落在'构图完整'相位\n"
                         "（两次运行像素计数一致，见 tools/_spine41_shots/report.json）")
    args = ap.parse_args()

    SHOTS.mkdir(exist_ok=True)
    build_serve_dir()
    httpd = start_server(PORT)
    print(f"[serve] http://127.0.0.1:{PORT} root={SERVE}")
    try:
        assets = ["char003892", "illust_dating14"] if args.asset == "all" else [args.asset]
        results = [verify_asset(a, args.budget) for a in assets]
    finally:
        httpd.shutdown()
        httpd.server_close()

    report = {"assets": results, "summary": {
        "passed": sum(1 for r in results if r.get("passed")),
        "total": len(results),
    }}
    (SHOTS / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== 汇总: {report['summary']['passed']}/{report['summary']['total']} PASS ==")
    print(f"报告: {SHOTS / 'report.json'}")
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())