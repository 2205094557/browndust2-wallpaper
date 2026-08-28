# -*- coding: utf-8 -*-
"""导出 Ultimate 壁纸，检查 SCALE/BG_SCALE 是否写入，并渲染对比 scale=100 vs 150。"""
import re
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")
import backend_server as bs  # noqa: E402

sys.path.insert(0, r"D:\codex\browndust2-wallpaper\tools")
from verify_spine41 import MSEDGE, analyze_png  # noqa: E402

PORT = 18936
SHIP, BUNDLE, NAME = "伊柯利普斯", "cutscene_char000701", "空间魔女 · Ultimate"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: ANN001
        pass


def screenshot(proj_dir: str, shot: Path) -> bool:
    httpd = HTTPServer(("127.0.0.1", PORT), partial(QuietHandler, directory=str(proj_dir)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{PORT}/index.html"
        base = [MSEDGE, "--no-first-run", "--disable-extensions", "--mute-audio",
                "--hide-scrollbars", "--window-size=1280,720",
                f"--user-data-dir={tempfile.mkdtemp(prefix='sc_')}"]
        variants = [
            base + ["--headless=new", "--disable-gpu", f"--screenshot={shot}", "--virtual-time-budget=25000", url],
            base + ["--headless=new", "--use-angle=swiftshader", f"--screenshot={shot}", "--virtual-time-budget=25000", url],
        ]
        for cmd in variants:
            try:
                subprocess.run(cmd, capture_output=True, timeout=150)
            except Exception:  # noqa: BLE001
                continue
            if shot.exists() and shot.stat().st_size > 1000:
                return True
        return False
    finally:
        httpd.shutdown()
        httpd.server_close()


def main():
    shots = Path(r"D:\codex\browndust2-wallpaper\tools\_spine41_shots")
    shots.mkdir(exist_ok=True)
    for scale, bgscale in ((100, 100), (150, 100)):
        proj = bs._export_project(SHIP, BUNDLE, NAME, {
            "root": str(bs.ROOT), "bg": "auto", "voice": True, "intro": True, "interact": True,
            "scale": scale, "bgScale": bgscale,
        })
        html = (Path(proj) / "index.html").read_text(encoding="utf-8")
        ms = re.search(r"var SCALE = (\d+)", html)
        mb = re.search(r"var BG_SCALE = (\d+)", html)
        ma = re.search(r"var ANIMATION = (\"[^\"]*\")", html)
        shot = shots / f"sc_{scale}.png"
        ok = screenshot(proj, shot)
        print(f"=== scale={scale} bgscale={bgscale} | SCALE={ms.group(1) if ms else '?'} BG_SCALE={mb.group(1) if mb else '?'} ANIM={ma.group(1) if ma else '?'} | shot={'OK' if ok else 'FAIL'}")
        if ok:
            analyze_png(shot, lambda line: print("  " + line))


if __name__ == "__main__":
    main()
