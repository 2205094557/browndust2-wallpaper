# -*- coding: utf-8 -*-
"""一键打包脚本：强制 packaged 前端构建 → 校验 API 端口 → PyInstaller → 产物自检。

用法：
  python scripts/build_pack.py

为什么必须强制 packaged 前端：
  - 前端 API 地址来自 frontend/.env.packaged（VITE_API_BASE=http://127.0.0.1:8770）；
  - 只要 frontend/dist 被普通 `npm run build`（无 --mode packaged）覆盖过一次，
    打包版就会去连开发版后端 8766，表现是"后端服务未启动 / 下载失败 / 显示开发机数据"；
  - 本脚本每次打包前重新构建前端并校验产物里只有 8770，杜绝该问题复发。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
VITE_JS = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
PYINSTALLER = ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
DIST_DIR = ROOT / "dist" / "browndust2-wallpaper"
INTERNAL = DIST_DIR / "_internal"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    print(">>", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, timeout=timeout)


def check(name: str, ok: bool, extra: str = "") -> bool:
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + extra) if extra else ""))
    return ok


def assets_have(dist: Path, text: str) -> bool:
    assets = dist / "assets"
    if not assets.is_dir():
        return False
    return any(
        text in p.read_text(encoding="utf-8", errors="ignore")
        for p in assets.glob("*.js")
    )


def packaged_app_running() -> bool:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq browndust2-wallpaper.exe"],
            capture_output=True, text=True, timeout=10,
        )
        return "browndust2-wallpaper.exe" in r.stdout
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ok = True
    print("===== 一键打包 browndust2-wallpaper =====\n")

    if packaged_app_running():
        print("[FAIL] 打包版正在运行，dist 会被占用。请先关闭 browndust2-wallpaper.exe 再打包。")
        return 1

    # 1) 前端构建：强制 packaged 模式
    if not VITE_JS.exists():
        print("[FAIL] 未找到 Vite，请先在 frontend 目录执行 npm install")
        return 1
    r = run(["node", str(VITE_JS), "build", "--mode", "packaged"], cwd=FRONTEND, timeout=300)
    ok = check("前端构建（--mode packaged）", r.returncode == 0) and ok

    # 2) 前端产物校验：必须有 8770，且无 8766
    src_dist = FRONTEND / "dist"
    ok = check("前端 API 指向 127.0.0.1:8770", assets_have(src_dist, "127.0.0.1:8770")) and ok
    ok = check("前端无 8766 残留", not assets_have(src_dist, "127.0.0.1:8766")) and ok

    # 3) PyInstaller
    # 注意：.venv/Scripts/pyinstaller.exe 在部分机器上是坏入口（静默失败 exit 1），
    # 此时必须 fallback 到 python -m PyInstaller，否则打包直接失败。
    if PYINSTALLER.exists():
        r = run([str(PYINSTALLER), "browndust2.spec", "--noconfirm", "--clean"])
        if r.returncode != 0:
            print("  [info] pyinstaller.exe 入口失效，改用 python -m PyInstaller")
            r = run([sys.executable, "-m", "PyInstaller", "browndust2.spec", "--noconfirm", "--clean"])
    else:
        r = run([sys.executable, "-m", "PyInstaller", "browndust2.spec", "--noconfirm", "--clean"])
    ok = check("PyInstaller 构建", r.returncode == 0) and ok

    # 4) 产物静态自检
    required = {
        "exe": DIST_DIR / "browndust2-wallpaper.exe",
        "plugins": INTERNAL / "plugins",
        "core": INTERNAL / "core",
        "tools": INTERNAL / "tools",
        "templates": INTERNAL / "templates",
        "frontend dist": INTERNAL / "frontend" / "dist",
        "vendor spine 4.1": INTERNAL / "frontend" / "dist" / "vendor" / "spine-webgl-4.1.js",
        "avatars": INTERNAL / "resources" / "avatars",
        "bd2-interact": INTERNAL / "templates" / "shared" / "bd2-interact.js",
    }
    for name, p in required.items():
        ok = check(f"产物包含 {name}", p.exists()) and ok
    ok = check("无 local_skins.json", not (INTERNAL / "resources" / "metadata" / "local_skins.json").exists()) and ok

    # 5) 打包版前端 API 回归检查（最关键）
    packed_dist = INTERNAL / "frontend" / "dist"
    ok = check("打包版前端指向 127.0.0.1:8770", assets_have(packed_dist, "127.0.0.1:8770")) and ok
    ok = check("打包版前端无 8766 残留", not assets_have(packed_dist, "127.0.0.1:8766")) and ok

    print()
    if ok:
        print(f"构建自检全部通过，产物：{DIST_DIR}")
        print("发布前建议再跑：python tools/verify_package.py --clean")
        return 0
    print("存在 FAIL，禁止发布。请根据上方 FAIL 项修复后重新打包。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
