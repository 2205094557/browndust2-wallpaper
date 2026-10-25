# -*- coding: utf-8 -*-
"""一键启动源码版开发栈（棕色尘埃2 立绘壁纸工坊）。

启动内容：
  1. 后端 API   http://127.0.0.1:8766   (backend_server.py)
  2. 前端 dev   http://127.0.0.1:5173   (Vite)
  3. 桌面窗口   web_main.py（pywebview，加载 5173）

关闭行为：
  - 关闭应用窗口后，自动终止由本脚本启动的后端与 Vite；
  - Ctrl+C / 关闭控制台（SIGBREAK）同样会触发清理；
  - 显式一键关闭：python scripts/start_dev.py --stop

用法：
  python scripts/start_dev.py
  python scripts/start_dev.py --stop
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
VITE_JS = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"


def _find_pythonw() -> Path:
    """优先项目 venv，缺失时回退系统 pythonw（BD2 仓库未复制 .venv）。"""
    venv = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return venv
    sys_pw = shutil.which("pythonw")
    if sys_pw:
        return Path(sys_pw)
    raise SystemExit("未找到 pythonw（项目 .venv 与系统 PATH 均无）")


VENV_PY = _find_pythonw()
VITE_JS = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"

BACKEND_PORT = int(os.environ.get("BD2_BACKEND_PORT", "8766"))
VITE_PORT = int(os.environ.get("BD2_VITE_PORT", "5173"))
BACKEND_HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/health"
VITE_URL = f"http://127.0.0.1:{VITE_PORT}/"

STATE_DIR = Path(tempfile.gettempdir()) / (
    "azl_dev_" + hashlib.md5(str(ROOT).encode("utf-8")).hexdigest()[:10]
)
STATE_FILE = STATE_DIR / "state.json"
BACKEND_LOG = STATE_DIR / "backend.log"
VITE_LOG = STATE_DIR / "vite.log"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 识别本项目 dev 栈进程的命令行特征：
#  - 后端：<本项目解释器> backend_server.py [端口]（壳进程含 venv 路径，运行时子进程仅含脚本名）
#  - 窗口：<本项目解释器> web_main.py [dev url]（树杀可覆盖其运行时子进程）
#  - Vite：node 命令行里包含本项目 frontend 目录下的 vite.js 绝对路径
#
# 【必须按解释器目录限定脚本名规则】兄弟项目（如 D:\codex\azurlane-dynamic-wallpaper）
# 同样以 `pythonw.exe backend_server.py 8766` / `web_main.py` 启动，只按脚本名匹配会把
# 它们当成"本项目遗留进程"直接杀掉——实测会导致启动本工具时误杀碧蓝工具的后端。
_PY_DIR = re.escape(str(VENV_PY.parent))
DEV_PATTERNS = [
    re.compile(_PY_DIR + r'[\\/]pythonw?\.exe"?\s.*backend_server\.py(\s+\d+)?\s*$', re.I),
    re.compile(_PY_DIR + r'[\\/]pythonw?\.exe"?\s.*web_main\.py(\s|$)', re.I),
    re.compile(re.escape(str(FRONTEND)) + r'.*vite.*?\.js', re.I),
]
WINDOW_RE = DEV_PATTERNS[1]


def log(msg: str) -> None:
    print(f"[dev] {msg}", flush=True)


def _shell_json(cmd: list[str]) -> list[dict]:
    """取进程表（ProcessId/ParentProcessId/CommandLine），失败返回空列表。

    必须显式 utf-8 + errors='replace' 解码：系统默认 GBK 遇到进程表里的非
    GBK 字节（中文/日文命令行）会 UnicodeDecodeError 崩溃并返回空表，
    导致 window_alive() 恒为 False、误触发窗口自动重启（连开多个窗口）。
    命令行匹配只依赖 ASCII 特征，个别字符变 � 不影响判定。
    """
    for attempt in range(2):
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if r.returncode != 0 or not r.stdout.strip():
                continue
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            return [p for p in data if isinstance(p, dict)]
        except Exception:  # noqa: BLE001
            continue
    return []


def all_processes() -> list[dict]:
    ps = [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        # 显式 UTF-8 输出：Windows PowerShell 5.1 重定向默认 GBK，中文命令行会被
        # 截断/乱码，且 GBK 解码在 subprocess 侧会崩（见 _shell_json 注释）
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
    ]
    rows = _shell_json(ps)
    if rows:
        return rows
    wmic = ["wmic", "process", "get", "ProcessId,CommandLine", "/format:csv"]
    rows = _shell_json(wmic)
    return rows


def find_dev_pids() -> set[int]:
    """按命令行特征找出属于本项目 dev 栈的进程 PID。"""
    found: set[int] = set()
    for p in all_processes():
        cmd = p.get("CommandLine") or ""
        pid = p.get("ProcessId")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        if any(pat.search(cmd) for pat in DEV_PATTERNS):
            found.add(pid)
    return found


def window_alive() -> bool:
    """判断源码版窗口是否真的存活。

    注意：.venv 的 pythonw 是壳进程，可能先于运行时子进程退出，
    用 Popen.poll() 等壳进程会误判“窗口已关闭”而把整个栈清掉/重复开窗。
    这里按命令行匹配 web_main.py 进程（壳 + 运行时子进程都算）。"""
    for p in all_processes():
        cmd = p.get("CommandLine") or ""
        pid = p.get("ProcessId")
        try:
            if int(pid) > 0 and WINDOW_RE.search(cmd):
                return True
        except (TypeError, ValueError):
            continue
    return False


def port_owner(port: int) -> int | None:
    """返回占用本地端口的进程 PID；未被占用返回 None。"""
    ps = [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"Get-NetTCPConnection -State Listen -LocalPort {port} "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess",
    ]
    try:
        r = subprocess.run(ps, capture_output=True, text=True, timeout=15)
        pid = (r.stdout or "").strip().splitlines()
        if pid:
            return int(pid[0])
    except Exception:  # noqa: BLE001
        pass
    # 兜底：直接探测端口是否被监听
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return -1  # 被占用但无法确认 PID
    except OSError:
        return None


def kill_tree(pid: int) -> None:
    """终止进程及其整棵子进程树（覆盖 venv pythonw 壳 -> 运行时子进程链）。"""
    if pid and pid > 0:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, text=True, timeout=20,
        )


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=10,
        )
        return f"{pid}" in r.stdout
    except Exception:  # noqa: BLE001
        return False


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def write_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def clear_state() -> None:
    try:
        STATE_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def wait_http(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def _log_tail(path: Path, lines: int = 25) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])
    except Exception:  # noqa: BLE001
        return "(无日志)"


def spawn(cmd: list[str], cwd: Path, log_file: Path | None = None,
          env: dict | None = None) -> subprocess.Popen:
    kwargs: dict = {"cwd": str(cwd), "creationflags": CREATE_NO_WINDOW}
    if env:
        kwargs["env"] = {**os.environ, **env}
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        f = open(log_file, "ab", buffering=0)  # noqa: SIM115
        kwargs["stdout"] = f
        kwargs["stderr"] = subprocess.STDOUT
    return subprocess.Popen(cmd, **kwargs)


_CLEANED = False


def cleanup(reason: str = "退出") -> None:
    """终止本脚本启动的所有子进程，并兜底清扫遗留的 dev 栈进程。"""
    global _CLEANED
    if _CLEANED:
        return
    _CLEANED = True
    state = read_state()
    targets: set[int] = set()
    for key in ("backend", "vite", "window"):
        pid = state.get(key)
        if pid:
            targets.add(int(pid))
    targets |= find_dev_pids()
    for pid in sorted(targets):
        kill_tree(pid)
    clear_state()
    log(f"已清理 {len(targets)} 个 dev 进程（{reason}）")


def stop_stack() -> int:
    state = read_state()
    pids = {int(v) for v in state.values() if str(v).isdigit()}
    pids |= find_dev_pids()
    for pid in sorted(pids):
        kill_tree(pid)
    clear_state()
    log(f"已关闭 dev 栈（{len(pids)} 个进程）")
    return 0


def ensure_node() -> str:
    node = shutil.which("node")
    if not node:
        for cand in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
            if Path(cand).exists():
                return cand
    if not node:
        raise RuntimeError("未找到 node，请先安装 Node.js")
    return node


def spawn_window() -> subprocess.Popen:
    """启动桌面窗口并把 Vite 地址/后端端口传进去（端口可用环境变量覆盖）。"""
    return spawn(
        [str(VENV_PY), "web_main.py", VITE_URL],
        ROOT,
        env={"BD2_BACKEND_PORT": str(BACKEND_PORT)},
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="一键启动/关闭源码版开发栈")
    ap.add_argument("--stop", action="store_true", help="关闭后端/Vite/窗口等 dev 进程")
    args = ap.parse_args()

    if args.stop:
        return stop_stack()

    if not VENV_PY.exists():
        log(f"未找到 venv Python：{VENV_PY}")
        return 1
    if not VITE_JS.exists():
        log(f"未找到 Vite 入口（先执行 npm install）：{VITE_JS}")
        return 1

    # 已有启动器在跑则退出
    state = read_state()
    launcher = state.get("launcher")
    if launcher and pid_alive(int(launcher)):
        log(f"已有启动器在运行（PID {launcher}），如需重启先执行 --stop")
        return 1

    # 启动前清理：属于本项目的遗留进程直接杀掉；占用端口但不属于本项目则中止
    leftovers = find_dev_pids()
    for port in (BACKEND_PORT, VITE_PORT):
        owner = port_owner(port)
        if owner and owner > 0 and owner not in leftovers:
            log(f"端口 {port} 被非本项目进程占用（PID {owner}），为避免误杀已中止启动")
            return 1
        if owner and owner > 0:
            leftovers.add(owner)
    if leftovers:
        for pid in sorted(leftovers):
            kill_tree(pid)
        log(f"已清理上一轮遗留 dev 进程：{sorted(leftovers)}")
        time.sleep(1)

    # 1) 后端
    log(f"启动后端 {BACKEND_HEALTH_URL} ...")
    backend = spawn([str(VENV_PY), "backend_server.py", str(BACKEND_PORT)], ROOT, BACKEND_LOG)
    write_state({"launcher": os.getpid(), "backend": backend.pid, "started": time.time()})
    if not wait_http(BACKEND_HEALTH_URL):
        log("后端启动失败，日志尾部：\n" + _log_tail(BACKEND_LOG))
        cleanup("后端启动失败")
        return 1
    log("后端就绪")

    # 2) Vite
    node = ensure_node()
    log(f"启动 Vite {VITE_URL} ...")
    # 端口被覆盖时必须把 API 地址显式告诉前端（默认 8766 写在前端代码里）
    vite = spawn(
        [node, str(VITE_JS), "--port", str(VITE_PORT)],
        FRONTEND,
        VITE_LOG,
        env={"VITE_API_BASE": f"http://127.0.0.1:{BACKEND_PORT}"},
    )
    state = read_state()
    state["vite"] = vite.pid
    write_state(state)
    if not wait_http(VITE_URL):
        log("Vite 启动失败，日志尾部：\n" + _log_tail(VITE_LOG))
        cleanup("Vite 启动失败")
        return 1
    log("Vite 就绪")

    # 3) 窗口
    log("启动桌面窗口（web_main.py）...")
    window = spawn_window()
    state = read_state()
    state["window"] = window.pid
    write_state(state)

    log("全部就绪。关闭应用窗口后，后端与 Vite 会自动退出；Ctrl+C 也可清理。")
    spawn_time = time.time()
    restarts = 0
    try:
        while True:
            if not window_alive():
                uptime = time.time() - spawn_time
                if uptime < 20 and restarts < 3:
                    restarts += 1
                    log(f"窗口异常退出（运行 {uptime:.0f}s），第 {restarts} 次自动重启 ...")
                    window = spawn_window()
                    state = read_state()
                    state["window"] = window.pid
                    write_state(state)
                    spawn_time = time.time()
                    continue
                log(f"窗口已关闭（运行 {uptime:.0f}s），正在清理 ...")
                break
            if backend.poll() is not None:
                log("警告：后端进程意外退出")
            if vite.poll() is not None:
                log("警告：Vite 进程意外退出")
            time.sleep(1)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，正在清理 ...")
    finally:
        cleanup("窗口关闭" if window.poll() is not None else "Ctrl+C")
    return 0


def _on_signal(signum, _frame) -> None:  # noqa: ANN001
    log(f"收到信号 {signum}，正在清理 ...")
    cleanup(f"信号 {signum}")
    sys.exit(0)


atexit.register(cleanup)
signal.signal(signal.SIGINT, _on_signal)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, _on_signal)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _on_signal)


if __name__ == "__main__":
    raise SystemExit(main())
