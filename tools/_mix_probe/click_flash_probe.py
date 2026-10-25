#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BD2 点击闪帧复现驱动（tools/_mix_probe/click_flash_probe.html + msedge headless）。

对指定皮肤跑「点击推进 → 目标点击」的宿主同路径模拟：
  - dump-dom 拿逐帧槽位附件变更（闪现 = 早期出现随后复原的槽）；
  - --shot 时对指定 (clicks, mode, ms) 冻结帧截图，供人眼确认闪现组件。

用法：
  python tools/_mix_probe/click_flash_probe.py --shot clicks=0,2 mode=mid ms=60
  python tools/_mix_probe/click_flash_probe.py --skins illust_dating12,illust_dating20
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent.parent
TOOLS = Path(__file__).resolve().parent
SPINE_DIR = REPO / "resources" / "extracted" / "spine"
RUNTIME_SRC = REPO / "templates" / "spine41" / "spine-webgl-4.1.js"
ENGINE_SRC = REPO / "templates" / "shared" / "bd2-interact.js"
PROBE_HTML = TOOLS / "click_flash_probe.html"
SHOTS = TOOLS / "_flash_shots"
REPORTS = TOOLS / "_flash_reports"
SERVE = SHOTS / "_serve"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
PORT = 18932
W, H = 1280, 720
BUDGET = 8000

CLICK_GRID = [0, 1, 2, 3, 4, 6, 8, 12, 16, 22]


def build_serve_dir(skins: list[str]) -> None:
    if SERVE.exists():
        shutil.rmtree(SERVE)
    (SERVE / "assets").mkdir(parents=True)
    shutil.copy2(PROBE_HTML, SERVE / "click_flash_probe.html")
    shutil.copy2(RUNTIME_SRC, SERVE / "spine-webgl-4.1.js")
    shutil.copy2(ENGINE_SRC, SERVE / "bd2-interact.js")
    for name in skins:
        src_dir = SPINE_DIR / name
        dst_dir = SERVE / "assets" / name
        dst_dir.mkdir()
        for f in src_dir.iterdir():
            dst = dst_dir / f.name
            try:
                os.link(f, dst)
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


def run_edge(extra_args: list[str], url: str, timeout: int = 120) -> tuple[int | None, str, str]:
    prof = TOOLS / '_edge_prof' / f"{os.getpid()}_{threading.get_ident()}"
    prof.mkdir(parents=True, exist_ok=True)
    for bi, browser in enumerate(BROWSERS):
        if not Path(browser).exists():
            continue
        base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=1", f"--window-size={W},{H}",
                "--autoplay-policy=no-user-gesture-required", "--no-first-run",
                "--disable-extensions", "--mute-audio",
                f"--user-data-dir={prof / str(bi)}"]
        variants = [
            base + extra_args,
            base + ["--use-angle=swiftshader"] + extra_args,
        ]
        for idx, cmd in enumerate(variants):
            try:
                r = subprocess.run(cmd + [url], capture_output=True, timeout=timeout)
                out = r.stdout.decode("utf-8", "replace")
                err = r.stderr.decode("utf-8", "replace")
                if "BD2-READY" in out or "BD2-READY" in err or "BD2-ERR" in out or (idx == len(variants) - 1 and out):
                    return idx, out, err
            except subprocess.TimeoutExpired:
                continue
    return None, "", "browser-failed"


def parse_diag(dom: str) -> dict:
    m = re.search(r'<pre id="out">([\s\S]*?)(?:</pre>|$)', dom)
    if not m:
        return {"ready": False, "text": ""}
    text = m.group(1)
    if "BD2-READY" not in text:
        return {"ready": False, "text": text[:400]}
    res = {"ready": True, "text": text, "frames": {}}
    for fm in re.finditer(r"^F(\d+) \((\d+)ms\) changed=(\d+)\n((?:  .*\n)*)", text, re.M):
        f = int(fm.group(1))
        lines = [l[2:] for l in fm.group(4).splitlines() if l.startswith("  ")]
        res["frames"][f] = lines
    return res


def summarize_diag(diag: dict) -> str:
    """闪现槽 = 早期帧出现变更、后续帧复原（回到点击前值）的槽。"""
    if not diag.get("ready"):
        return "ERR: " + diag.get("text", "")[:200]
    frames = diag.get("frames", {})
    order = sorted(frames)
    early = {l.split(":")[0]: l for l in frames.get(order[0], [])} if order else {}
    all_later = {}
    for f in order[1:]:
        for l in frames[f]:
            all_later[l.split(":")[0]] = l
    flashed = [early[k] for k in early if k not in all_later]  # 出现过又复原
    lines = [l for l in (diag.get("text") or "").splitlines() if not l.startswith("  ") and not l.startswith("F")]
    head = "\n".join(lines[:6])
    extra = ""
    if flashed:
        extra = "\n  >> 闪现槽(复原): " + "; ".join(flashed[:6]) + (" ..." if len(flashed) > 6 else "")
    changed0 = frames.get(order[0], []) if order else []
    extra += "\n  F1 变更槽数=" + str(len(changed0))
    return head + extra


def scenario_key(skin: str, clicks: int, mode: str) -> str:
    return f"{skin}_c{clicks}_{mode}"


def probe_one(args: tuple) -> tuple[str, dict]:
    skin, clicks, mode, shot_ms = args
    skel = next(SPINE_DIR.joinpath(skin).glob("*.skel")).name
    atlas = next(SPINE_DIR.joinpath(skin).glob("*.atlas")).name
    url = (f"http://127.0.0.1:{PORT}/click_flash_probe.html?asset={skin}&skel={skel}"
           f"&atlas={atlas}&clicks={clicks}&mode={mode}&ms=100")
    _, dom, _ = run_edge(["--dump-dom", f"--virtual-time-budget={BUDGET}"], url)
    diag = parse_diag(dom)
    REPORTS.mkdir(exist_ok=True)
    if diag.get("ready") and diag.get("text"):
        (REPORTS / (scenario_key(skin, clicks, mode) + ".txt")).write_text(
            diag["text"], encoding="utf-8")
    # 画面随 DOM 的 IMG base64 输出，与截图模式二选一（readPixels 更可靠）
    if shot_ms and diag.get("ready"):
        import base64
        for ms in shot_ms:
            u2 = url.replace("ms=100", f"ms={ms}")
            _, dom2, _ = run_edge(["--dump-dom", f"--virtual-time-budget={BUDGET}"], u2)
            m = re.search(r"^IMG (data:image/jpeg;base64,[A-Za-z0-9+/=]+)\s*$", dom2, re.M)
            if m:
                b64 = m.group(1).split(",", 1)[1]
                (SHOTS / f"{scenario_key(skin, clicks, mode)}_ms{ms}.jpg").write_bytes(
                    base64.b64decode(b64))
    return scenario_key(skin, clicks, mode), summarize_diag(diag)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skins", default="illust_dating12,illust_dating17,illust_dating20")
    ap.add_argument("--clicks", default="", help="逗号列表，默认网格 " + ",".join(map(str, CLICK_GRID)))
    ap.add_argument("--modes", default="tail,mid")
    ap.add_argument("--shot", default="", help="如 clicks=0,2 mode=mid ms=60,160 的逗号段")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    skins = [s.strip() for s in args.skins.split(",") if s.strip()]
    missing = [s for s in skins if not SPINE_DIR.joinpath(s).is_dir()]
    if missing:
        print("未找到皮肤:", missing)
        return 2
    clicks_list = [int(x) for x in args.clicks.split(",")] if args.clicks else CLICK_GRID
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    shot_map: dict[tuple, list[int]] = {}
    if args.shot:
        for seg in args.shot.split(","):
            kv = seg.split("=")
            if kv[0] == "ms":
                continue
        # 语法: clicks=0,2 mode=mid ms=60,160
        sc = re.search(r"clicks=([\d,]+)", args.shot)
        sm = re.search(r"mode=(\w+)", args.shot)
        sms = re.search(r"ms=([\d,]+)", args.shot)
        if sc and sm and sms:
            for c in map(int, sc.group(1).split(",")):
                for m in sm.group(1).split(","):
                    shot_map[(c, m)] = [int(x) for x in sms.group(1).split(",")]

    SHOTS.mkdir(exist_ok=True)
    build_serve_dir(skins)
    httpd = start_server(PORT)
    print(f"[serve] http://127.0.0.1:{PORT}  {len(skins)} skins")
    jobs = [(skin, c, m, shot_map.get((c, m), []))
            for skin in skins for c in clicks_list for m in modes]
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for key, summary in ex.map(probe_one, jobs):
            results.append((key, summary))
            flag = "OK" if "ERR:" not in summary else "!E"
            print(f"[{flag}] {key}")
            for ln in summary.splitlines()[:8]:
                if ln.strip():
                    print("     " + ln)
    print(f"\n完成 {len(results)} 个场景，报告在 {REPORTS}，截图在 {SHOTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
