#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BD2 取景批量探针（tools/framing_probe.html + msedge headless）。

职责：
  1. 扫描 resources/extracted/spine/* 全部皮肤，组装本地 HTTP 服务目录
     （硬链接资产），逐个用 headless Edge 渲染探针页；
  2. 探针页与模板 wallpaper_spine.html 的取景链逐字一致，输出：
     raw/contentFrame/denseAreaFrame/final 四层包围盒 + top 附件 +
     t=0 与 animtime 秒两帧的 alpha 双阈值像素统计（a8/a96 的 wPct/hPct/areaPct）；
  3. 汇总 report.json + 控制台黑边榜（areaPct 升序 = 黑边最大在前）。

「黑边过大」判定：相机按 final bounds 高度铺满画布，内容 bbox 面积占比
（a96.areaPct，实体像素）越低 = 周围留白/黑边越大。阈值见 --max-area。

用法：
  python tools/framing_probe.py                       # 全量扫描（不截图）
  python tools/framing_probe.py --asset illust_dating15 --shot   # 单皮肤 + 截图
  python tools/framing_probe.py --assets a,b,c --shot            # 指定若干皮肤
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
SHOTS = TOOLS / "_framing_shots"
SERVE = SHOTS / "_serve"
SPINE_DIR = REPO / "resources" / "extracted" / "spine"
RUNTIME_SRC = REPO / "templates" / "spine41" / "spine-webgl-4.1.js"
LAYOUT_SRC = REPO / "templates" / "wallpaper-layout.js"
PROBE_HTML = TOOLS / "framing_probe.html"

MSEDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 18931
W, H = 1280, 720


def discover_skins() -> dict[str, tuple[str, str]]:
    """{目录名: (skel文件名, atlas文件名)}。"""
    out = {}
    for d in sorted(SPINE_DIR.iterdir()):
        if not d.is_dir():
            continue
        skels = list(d.glob("*.skel"))
        atlases = list(d.glob("*.atlas"))
        if not skels or not atlases:
            continue
        out[d.name] = (skels[0].name, atlases[0].name)
    return out


def build_serve_dir(skins: dict[str, tuple[str, str]]) -> None:
    if SERVE.exists():
        shutil.rmtree(SERVE)
    (SERVE / "assets").mkdir(parents=True)
    shutil.copy2(PROBE_HTML, SERVE / "framing_probe.html")
    shutil.copy2(RUNTIME_SRC, SERVE / "spine-webgl-4.1.js")
    shutil.copy2(LAYOUT_SRC, SERVE / "wallpaper-layout.js")
    for name in skins:
        src_dir = SPINE_DIR / name
        dst_dir = SERVE / "assets" / name
        dst_dir.mkdir()
        for f in src_dir.iterdir():
            dst = dst_dir / f.name
            try:
                os_link = getattr(__import__("os"), "link", None)
                if os_link:
                    os_link(f, dst)
                else:
                    shutil.copy2(f, dst)
            except OSError:
                shutil.copy2(f, dst)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server(port: int) -> HTTPServer:
    from functools import partial
    httpd = HTTPServer(("127.0.0.1", port), partial(QuietHandler, directory=str(SERVE)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def run_edge(extra_args: list[str], url: str, timeout: int = 90):
    base = [
        MSEDGE, "--no-first-run", "--disable-extensions", "--mute-audio",
        "--hide-scrollbars", f"--window-size={W},{H}",
        f"--user-data-dir={tempfile.mkdtemp(prefix='edgefp_')}",
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
            if "BD2-READY" in out or "BD2-READY" in err or "BD2-ERR" in out or idx == len(variants) - 1:
                return idx, out, err
        except subprocess.TimeoutExpired:
            continue
    return None, "", "timeout"


def probe_one(args_tuple):
    name, skel, atlas, animtime, shot, budget = args_tuple
    url = (f"http://127.0.0.1:{PORT}/framing_probe.html?asset={name}"
           f"&skel={skel}&atlas={atlas}&animtime={animtime}")
    # dump-dom 拿页内统计；shot 模式再单独截一张（screenshot 模式无 stdout 可解析）
    _, out, _ = run_edge(["--dump-dom", f"--virtual-time-budget={budget}"], url)
    dom = out
    if shot:
        run_edge([f"--screenshot={SHOTS / (name + '.png')}",
                  f"--virtual-time-budget={budget}"], url)
    m = re.search(r'<pre id="out">([\s\S]*?)(?:</pre>|$)', dom)
    if not m:
        return {"asset": name, "ready": False, "error": "no #out (page crash?)"}
    text = m.group(1)
    if "BD2-READY" not in text:
        return {"asset": name, "ready": False, "error": text[:300]}
    jm = re.search(r"\r?\n(\{.*\})\r?\n", text)
    info = {}
    if jm:
        try:
            info = json.loads(jm.group(1))
        except Exception:
            pass
    stats = {}
    for tag in ("STATS_T0", "STATS_ANIM"):
        sm = re.search(tag + r" (a8=\{[^\n]*\}) (a96=\{[^\n]*\})", text)
        if sm:
            try:
                stats[tag] = {"a8": json.loads(sm.group(1)[3:]), "a96": json.loads(sm.group(2)[4:])}
            except Exception:
                pass
    return {"asset": name, "ready": True, "info": info, "stats": stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="", help="单个皮肤目录名")
    ap.add_argument("--assets", default="", help="逗号分隔多个皮肤目录名")
    ap.add_argument("--animtime", type=float, default=2.5)
    ap.add_argument("--budget", type=int, default=8000)
    ap.add_argument("--shot", action="store_true", help="同时截图（默认只 dump-dom）")
    ap.add_argument("--max-area", type=float, default=40.0,
                    help="黑边判定阈值：a96 bbox 面积占比低于此值记为黑边过大")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    all_skins = discover_skins()
    if args.asset:
        names = [args.asset]
    elif args.assets:
        names = [n.strip() for n in args.assets.split(",") if n.strip()]
    else:
        names = sorted(all_skins)
    missing = [n for n in names if n not in all_skins]
    if missing:
        print(f"未找到皮肤目录: {missing}")
        return 2

    SHOTS.mkdir(exist_ok=True)
    print(f"[probe] 组装服务目录（{len(names)} 个皮肤）…")
    build_serve_dir(all_skins)
    httpd = start_server(PORT)
    print(f"[serve] http://127.0.0.1:{PORT} root={SERVE}")
    try:
        jobs = [(n, all_skins[n][0], all_skins[n][1], args.animtime, args.shot, args.budget)
                for n in names]
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, res in enumerate(ex.map(probe_one, jobs), 1):
                results.append(res)
                flag = "OK " if res.get("ready") else "ERR"
                st = (res.get("stats") or {}).get("STATS_ANIM") or {}
                a96 = st.get("a96") or {}
                print(f"[{i}/{len(names)}] {flag} {res['asset']} "
                      f"a96 area={a96.get('areaPct')}% w={a96.get('wPct')}% h={a96.get('hPct')}%")
    finally:
        httpd.shutdown()
        httpd.server_close()

    # 黑边榜：按判定严重度排序
    ranked = []
    for r in results:
        if not r.get("ready"):
            continue
        st = (r.get("stats") or {}).get("STATS_ANIM") or {}
        a96 = st.get("a96") or {}
        a8 = st.get("a8") or {}
        n96 = a96.get("n") or 0
        # 暗色平板（FR 黑边遮罩/黑幕面板）：alpha>96 像素多但彩色占比极低
        coloredRatio = (a96.get("colored") or 0) / max(1, n96)
        wPct, hPct = a96.get("wPct"), a96.get("hPct")
        flags = []
        if n96 > 0 and coloredRatio < 0.08:
            flags.append(f"dark_slab({coloredRatio:.1%})")
        if wPct is not None and hPct is not None and min(wPct, hPct) < 50:
            flags.append(f"small_both({min(wPct, hPct)}%)")
        if hPct is not None and hPct < 85:
            flags.append(f"vert_border(h={hPct}%)")
        info = r.get("info") or {}
        ranked.append({
            "asset": r["asset"],
            "flags": flags,
            "a96_areaPct": a96.get("areaPct"), "a96_wPct": wPct, "a96_hPct": hPct,
            "a96_fill": round(100 * n96 / (1280 * 720), 1),
            "coloredRatio": round(coloredRatio, 4),
            "a8_areaPct": a8.get("areaPct"), "a8_wPct": a8.get("wPct"), "a8_hPct": a8.get("hPct"),
            "finalBounds": info.get("finalBounds"), "rawBounds": info.get("rawBounds"),
            "contentFrame": info.get("contentFrame"), "denseAreaFrame": info.get("denseAreaFrame"),
            "top": info.get("topAttachments"),
            "slotNames": info.get("slotNames"),
        })
    ranked.sort(key=lambda x: (-len(x["flags"]),
                               (x["a96_hPct"] if x["a96_hPct"] is not None else 999)))
    report = {"results": ranked}
    (SHOTS / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    bad = [r for r in ranked if r["flags"]]
    print(f"\n== 取景异常皮肤：{len(bad)}/{len(ranked)} ==")
    for r in bad:
        print(f"  {r['asset']:28s} {' '.join(r['flags'])}  a96 area={r['a96_areaPct']}% "
              f"w={r['a96_wPct']}% h={r['a96_hPct']}% fill={r['a96_fill']}%")
    print(f"报告: {SHOTS / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
