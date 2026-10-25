"""Wallpaper Engine 集成：定位安装目录、应用壁纸、打开编辑器。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

COMMON_PATHS = [
    Path("C:/Program Files (x86)/Steam/steamapps/common/wallpaper_engine"),
    Path("C:/Program Files/Steam/steamapps/common/wallpaper_engine"),
    Path("D:/Program Files/Steam/steamapps/common/wallpaper_engine"),
    Path("D:/Program Files (x86)/Steam/steamapps/common/wallpaper_engine"),
    Path("E:/Steam/steamapps/common/wallpaper_engine"),
]


def _steam_path_from_registry() -> Path | None:
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
        ):
            with winreg.OpenKey(hive, key) as k:
                val, _ = winreg.QueryValueEx(k, "SteamPath")
                p = Path(val) / "steamapps" / "common" / "wallpaper_engine"
                if (p / "wallpaper64.exe").exists():
                    return p
    except Exception:  # noqa: BLE001
        pass
    return None


def find_wallpaper_engine_dir() -> Path | None:
    p = _steam_path_from_registry()
    if p:
        return p
    for cand in COMMON_PATHS:
        if (cand / "wallpaper64.exe").exists():
            return cand
    return None


def _run(exe: str, args: list[str]) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([exe, *args], creationflags=creationflags)


def _ascii_copy_name(project_name: str) -> str:
    """WE 的 openWallpaper IPC 会把中文路径以乱码写进 config.json（selectedwallpapers），
    重启后壁纸将无法加载。副本目录名只保留 ASCII 字符，标题仍由 project.json 提供。"""
    ascii_part = re.sub(r"[^A-Za-z0-9_-]", "", project_name)[:32].strip("_-")
    return f"{ascii_part or 'azl2d'}_{uuid.uuid4().hex[:8]}"


# 一键应用副本的标记文件：内容记录本次壁纸的唯一标识（{ship}_{name} 去 _uuid8 前缀，
# 含中文，UTF-8 存储），下次应用时只清理同标识的旧副本（同角色同皮肤），
# 不同名壁纸的副本全部保留。
MARKER_NAME = ".azl2d-marker"


def _skin_identity(project_name: str) -> str:
    """从项目目录名提取壁纸身份标识（去 _uuid8 的 {ship}_{name} 前缀，原文含中文）。

    项目目录名格式 {ship}_{name}_{uuid8}：去掉末尾 _uuid8 后即为该皮肤的身份。
    marker 文件以 UTF-8 存此标识；副本目录名因 WE 中文路径乱码问题被 ASCII 化，
    无法反推身份，所以身份只记录在 marker 内容里。
    """
    return re.sub(r"_([0-9a-f]{8})$", "", project_name)


def _selected_wallpaper_paths(we: Path) -> list[str]:
    """WE config.json 中当前上屏的壁纸文件路径（selectedwallpapers 各显示器 file 字段）。

    正在渲染的副本一旦被删除，渲染进程读不到文件就会报错乃至崩溃——清理前必须
    先把它排除。WE 写入时统一小写且用正斜杠，这里同样规范化后比较。
    """
    cfg = we / "config.json"
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).lower().startswith("wallpaperconfigrecent"):
                    continue  # 最近使用列表：只是历史记录，其副本可以清理
                if str(k).lower().startswith("selectedwallpaper"):
                    if isinstance(v, dict):
                        for item in v.values():
                            if isinstance(item, dict) and item.get("file"):
                                found.append(str(item["file"]).replace("\\", "/").lower())
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    try:
        walk(json.loads(cfg.read_text(encoding="utf-8-sig")))
    except Exception:  # noqa: BLE001
        return []
    return found


def _cleanup_old_copies(we: Path, identity: str | None = None, exclude: Path | None = None) -> None:
    """删除本工具之前一键应用的、与本次同角色同皮肤的壁纸副本（myprojects 下带标记的目录）。

    每次「导出并应用」复制新目录，同名壁纸旧副本会无限堆积；只清理带标记
    且标记内容与本次一致（同角色同皮肤）的目录。不同名壁纸（其他角色/皮肤）
    的副本保留——用户可能同时应用多张不同壁纸，不能因应用新壁纸误删。
    exclude: 排除目录（当前新应用的副本），绝不删除。
    另外永远跳过 WE 当前正在渲染的副本（config.json selectedwallpapers）。
    """
    myprojects = we / "projects" / "myprojects"
    if not myprojects.is_dir():
        return
    exclude_resolved = exclude.resolve() if exclude else None
    selected = _selected_wallpaper_paths(we)
    removed = 0
    for d in myprojects.iterdir():
        if not d.is_dir():
            continue
        if exclude_resolved and d.resolve() == exclude_resolved:
            continue
        if selected:
            dkey = str(d).replace("\\", "/").lower()
            if any(s.startswith(dkey) for s in selected):
                continue  # 正被 WE 渲染：删除会让渲染进程读不到文件
        marker = d / MARKER_NAME
        if not marker.is_file():
            continue
        try:
            val = marker.read_text(encoding="utf-8").strip()
        except OSError:
            val = ""
        if identity is not None and val != identity:
            continue  # 不同名壁纸副本：保留
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    if removed:
        print(f"[we] 已清理 {removed} 个同皮肤旧壁纸副本", flush=True)


def _defer_cleanup_old_copies(we: Path, identity: str, exclude: Path, delay_seconds: float = 2.5) -> None:
    """后台延迟清理旧副本。

    必须在 openWallpaper 发送后延迟清理，绝不能在切换前同步删除！
    因为旧副本正被 Wallpaper Engine 的 CEF 渲染进程 (webwallpaper64) 运行加载；
    如果在切换前强制删除，CEF 读不到文件会直接报错并导致 Wallpaper Engine 闪退。
    延迟 2.5 秒确保 WE 已成功切换到新壁纸且释放了旧目录文件句柄。
    """
    def _worker():
        time.sleep(delay_seconds)
        _cleanup_old_copies(we, identity=identity, exclude=exclude)

    threading.Thread(target=_worker, daemon=True).start()


def apply_wallpaper(project_dir: Path) -> bool:
    we = find_wallpaper_engine_dir()
    if not we:
        return False
    identity = _skin_identity(project_dir.name)
    name = _ascii_copy_name(project_dir.name)
    dest = we / "projects" / "myprojects" / name
    shutil.copytree(project_dir, dest)
    try:
        (dest / MARKER_NAME).write_text(identity, encoding="utf-8")
    except OSError:
        pass
    pj = dest / "project.json"
    index = dest / "index.html"
    target = pj if pj.exists() else index
    if not target.exists():
        return False
    # 优先传入 project.json（WE 官方命令行规范），保证 WE 完整读取属性与预览
    _run(str(we / "wallpaper64.exe"), ["-control", "openWallpaper", "-file", str(target)])
    # 切换完成后在后台异步延迟清理同名旧副本，避免在切换时删掉正在运行的旧文件导致闪退
    _defer_cleanup_old_copies(we, identity=identity, exclude=dest, delay_seconds=2.5)
    return True


def open_editor(project_dir: Path) -> bool:
    we = find_wallpaper_engine_dir()
    if not we:
        return False
    pj = project_dir / "project.json"
    if not pj.exists():
        return False
    _run(str(we / "wallpaper64.exe"), ["-window", "editor", "-project", str(pj)])
    return True
