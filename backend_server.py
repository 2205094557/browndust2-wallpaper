"""本地后端 API 服务：提供官方 CDN 下载等接口，供前端（浏览器/桌面）调用。

启动: python backend_server.py [端口]   （默认 8766）
"""

from __future__ import annotations

import json
import hashlib
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.backgrounds import (  # noqa: E402
    CATEGORIES,
    background_dirs,
    delete_custom_background,
    export_background_for_outpaint,
    get_available_backgrounds,
    get_recommendations_for_ship,
    import_outpaint_results,
    migrate_legacy_custom,
)
from core.config import Config  # noqa: E402
from core.library import Library  # noqa: E402
from core.locks import named_lock  # noqa: E402
from core.metadata import Metadata  # noqa: E402
from core.palette import extract_palette, fallback_palette, find_palette_source, mode_css  # noqa: E402
from core.registry import Registry  # noqa: E402
from core.upscaler import ALGORITHMS as UPSCALE_ALGORITHMS, clean_preview_dir, upscale_background_image  # noqa: E402
from core.voice import set_resolver as _voice_set_resolver  # noqa: E402
from core.we_integration import apply_wallpaper  # noqa: E402
from core.applog import setup_logging  # noqa: E402

clean_preview_dir()
# 旧版持久成品库 custom 已废弃：启动时把其中的文件并入 input（幂等，不丢文件）
migrate_legacy_custom(ROOT)

registry = Registry(ROOT / "plugins").discover()
metadata = Metadata(ROOT / "resources" / "metadata")
library = Library(ROOT / "resources" / "library.db")
config = Config(ROOT / "resources" / "config.json")
cdn = registry.get("sources", "cdn")
if config.get("proxy"):
    cdn.proxy = config.get("proxy") or None
cdn.cache_dir = ROOT / "resources" / "metadata"
logger = setup_logging()

# ---- 下载阶段事件推送（SSE）：前端右下角卡片实时显示 下载/合成/同步 等阶段 ----
_EVENT_QUEUES: list[queue.Queue] = []
_EVENT_LOCK = threading.Lock()


def _broadcast(name: str, data: dict) -> None:
    payload = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _EVENT_LOCK:
        for q in _EVENT_QUEUES:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


def _emit_stage(stage: str, **extra) -> None:
    _broadcast("stage", {"stage": stage, **extra})

_META_MTIMES: dict[str, float] = {}
# 批量下载取消：前端带 download_id 发起下载，点取消时置位对应 Event，
# 下载循环按 chunk 检查，能快速停止正在进行的 CDN 下载（而非等整个文件下完）。
_CANCEL_LOCK = threading.Lock()
_CANCEL_EVENTS: dict[str, threading.Event] = {}


def _register_cancel(download_id: str) -> threading.Event:
    ev = threading.Event()
    with _CANCEL_LOCK:
        _CANCEL_EVENTS[download_id] = ev
    return ev


def _unregister_cancel(download_id: str) -> None:
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(download_id, None)


def cancel_download(download_id: str) -> bool:
    with _CANCEL_LOCK:
        ev = _CANCEL_EVENTS.get(download_id)
    if ev is not None:
        ev.set()
        return True
    return False
# dependencies 包与本地索引是共享文件，并发下载时多线程同时写会损坏/丢数据，必须串行化。
# 用 OS 级命名互斥体（打包版模块可能多实例，threading.Lock 不共享）。
_DEPS_LOCK = named_lock("bd2_dependencies")
_INDEX_LOCK = named_lock("bd2_local_index")
# run_tool 与提取器都会改写全局 sys.argv，必须共用同一把锁（与 static 提取器同名）。
_TOOL_LOCK = named_lock("bd2_sysargv")


def ensure_fresh_metadata() -> None:
    """每个请求前调用：元数据 JSON 被外部工具/脚本改动（mtime 变化）时自动重载，
    保证界面看到的数据和后端 API（下载/导出/取色）永远一致，不会出现
    “界面有皮肤、下载却说皮肤不存在”的旧内存数据问题。"""
    changed = False
    for name in ("ships.json", "skins.json", "local_skins.json"):
        p = ROOT / "resources" / "metadata" / name
        mt = p.stat().st_mtime if p.exists() else 0.0
        if _META_MTIMES.get(name) != mt:
            _META_MTIMES[name] = mt
            changed = True
    if changed:
        metadata.reload()
        refresh_library()


def refresh_library() -> None:
    library.import_metadata(metadata.ships(), metadata.skins(), metadata.local_skins())


refresh_library()


def _resolve_voice_painting(painting: str):
    """illust_datingN[_K] 等间接 painting → 所属服装的语音 id。

    约会立绘本身没有独立语音包，互动语音按服装（charXXXXXX）挂载；通过元数据
    反查 dating 字段归属的服装 id。注意：这里只做映射、不检查 bytes 是否存在——
    resolve_id 的调用方（语音状态查询/导出）按返回值自行判断，而补语音流程
    恰恰需要拿到"还没下载"的目标 id。2026-10 起官方把多章节约会皮拆成多套
    骨架（illust_dating22_1/_2），分卷 painting 归属同一服装。
    """
    m = re.fullmatch(r"illust_dating\d+(?:_\d+)?", painting)
    if not m:
        return None
    base = re.sub(r"_\d+$", "", painting)
    for e in metadata.characters():
        if (e.get("dating") or "").lower() == base:
            return f"char{e['id']}"
    return None


_voice_set_resolver(_resolve_voice_painting)


def get_config() -> dict:
    """返回当前配置（含代理设置）。"""
    return {"ok": True, "config": config.data}


def set_config(patch: dict) -> dict:
    """更新配置并立即生效（代理 / 语音下载 / 退出清理开关）。"""
    patch = patch or {}
    if "proxy" in patch:
        proxy = (patch.get("proxy") or "").strip()
        config.set("proxy", proxy)
        cdn.proxy = proxy or None
    if "voice_download" in patch:
        config.set("voice_download", bool(patch.get("voice_download")))
    if "clean_bundles_on_exit" in patch:
        config.set("clean_bundles_on_exit", bool(patch.get("clean_bundles_on_exit")))
    return {"ok": True, "config": config.data}


def resolve_skin(ship: str, bundle: str, name: str | None = None) -> dict | None:
    hits = [s for s in metadata.skins() if s.get("ship") == ship and s.get("bundle") == bundle]
    if not hits:
        # 本地独有条目（多章约会皮分卷 illust_dating22_1 等）：skins.json 只有
        # 基础条目，local_skins 是提取事实来源，直接以本地数据兜底解析。
        locs = [
            l for l in metadata.local_skins()
            if l.get("ship") == ship and l.get("bundle") == bundle
        ]
        if not locs:
            return None
        if name is None:
            return locs[0]
        for s in locs:
            if s.get("name") == name:
                return s
        return locs[0] if len(locs) == 1 else None
    if name is None:
        return hits[0]
    for s in hits:
        if s.get("name") == name:
            return s
    # 名字对不上（占位名/旧名）：仅当 ship+bundle 唯一候选时容忍，
    # 避免 DOA 联动等“同 key 多皮肤”误配。
    return hits[0] if len(hits) == 1 else None


def downloaded_with_painting() -> list[dict]:
    out = []
    for s in library.downloaded_skins():
        skin = resolve_skin(s["ship"], s["bundle"], s.get("name"))
        out.append({**s, "painting": (skin or {}).get("painting", "")})
    return out


def _is_shared_bundle(bundle_key: str) -> bool:
    """BD2 三个全角色共享大包（主立绘/约会/尊爵）——永不清理。"""
    low = (bundle_key or "").lower()
    return (
        "illustspine_" in low
        or "datingillust_assets_all" in low
        or "illustspecial_" in low
    )


def skin_files(skin: dict) -> list[Path]:
    """返回该皮肤对应的本地 bundle 与提取产物路径。

    BD2：主立绘/约会/尊爵来自共享大包，bundle 不归属单个皮肤，
    只返回提取产物目录；演出(cutscene)是每角色独立包，连 bundle 一起返回。
    """
    painting = skin.get("painting", "")
    stype = skin.get("type", "")
    b = ROOT / "resources" / "bundles"
    e = ROOT / "resources" / "extracted"
    paths: list[Path] = []
    if stype == "spine":
        paths.append(e / "spine" / painting)
        if painting.lower().startswith("cutscene_"):
            # 每角色独立演出包
            char_id = painting[len("cutscene_"):]
            paths += [
                p for p in (b).glob(f"isolated-cutscene{char_id.replace('char', '')}-group*")
                if p.exists()
            ]
    else:
        paths.append(e / "static" / painting)
    return [p for p in paths if p.exists()]


def _sync_skins_and_index() -> None:
    """重建 skins.json（含约会分卷条目发现）→ local_skins.json 并刷新内存。

    分卷条目由 build_bd2_skins 从提取目录发现，所以任何会增删提取产物的流程
    （下载/删除/清空）都必须走这里，只跑 build_local_index 会让图鉴看不到新
    分卷或留下幽灵条目。
    """
    with _INDEX_LOCK:
        run_tool("build_bd2_skins", timeout=60)
        run_tool("build_local_index", timeout=120)
        metadata.reload()
        refresh_library()


def delete_skin_files(ship: str, bundle: str, name: str | None = None) -> dict:
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        return {"ok": False, "error": "皮肤不存在"}
    removed = [str(p) for p in skin_files(skin)]
    for p in skin_files(skin):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)
    _sync_skins_and_index()
    # 语音联动：该船已无其他已下载皮肤时，删除其语音（转换产物 + cue 包）
    try:
        from core import voice as voice_mod
        ship_id = voice_mod.resolve_id((skin or {}).get("painting", ""))
        if ship_id:
            still = [
                s for s in downloaded_with_painting()
                if s.get("ship") == ship and s.get("painting") != (skin or {}).get("painting")
            ]
            if not still:
                removed.extend(voice_mod.remove_voice(ship_id))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "removed": removed}


def delete_skins_batch(items: list[dict]) -> dict:
    """批量删除皮肤：只删文件 + 语音联动检查一次，最后重建一次索引。

    逐个调用 delete_skin_files 时每个皮肤都会触发一次 build_local_index
    （全量扫描 extracted 目录），全选删除 N 个皮肤就是 N 次全量重建——这是
    「设置页全选删除很慢」的根源。批量版把索引重建从 O(N) 降到 1 次。
    """
    removed: list[str] = []
    failed: list[dict] = []
    seen_paintings: set[str] = set()  # 本次删掉的 painting（去重）
    for it in items or []:
        try:
            ship = it.get("ship", "")
            bundle = it.get("bundle", "")
            name = it.get("name")
            skin = resolve_skin(ship, bundle, name)
            if not skin:
                failed.append({"ship": ship, "bundle": bundle, "name": name, "error": "皮肤不存在"})
                continue
            for p in skin_files(skin):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    p.unlink(missing_ok=True)
                else:
                    pass
                removed.append(str(p))
            painting = (skin or {}).get("painting", "")
            if painting:
                seen_paintings.add(painting.lower())
        except Exception as e:  # noqa: BLE001
            failed.append({"ship": it.get("ship"), "error": str(e)})

    # 语音联动：被清空的船删除其语音（转换产物 + cue 包）。
    # 用「剩余已下载」判断：批量删除后一次性刷新元数据再查，避免逐皮肤重复查询。
    try:
        from core import voice as voice_mod

        _sync_skins_and_index()  # 先重建一次索引供下方查询
        remaining = {s.get("painting", "").lower() for s in downloaded_with_painting()}
        for painting in sorted(seen_paintings):
            if painting in remaining:
                continue
            ship_id = voice_mod.resolve_id(painting)
            if ship_id:
                removed.extend(voice_mod.remove_voice(ship_id))
    except Exception as e:  # noqa: BLE001
        print(f"[batch-delete] 语音联动失败: {e}")
        # 兜底：仍要保证索引与内存一致
        _sync_skins_and_index()
    return {
        "ok": not failed,
        "removed_count": len(removed),
        "failed": failed,
        "failed_count": len(failed),
    }


def clear_all_downloads() -> dict:
    removed = []
    for sub in ("bundles", "extracted"):
        d = ROOT / "resources" / sub
        if d.is_dir():
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
    _sync_skins_and_index()
    return {"ok": True, "removed": removed}


def _bundle_paths(stype: str, painting: str, depmap: dict | None = None) -> list[Path]:
    """该皮肤专属的原始下载包路径（BD2 版）。

    共享大包（illustspine/datingillust/illustspecial）与语音包**永远不在
    清理范围**——它们服务全部角色，删了就要整体重下。只有每角色独立的
    演出包（isolated-cutsceneXXXXXX-group）随皮肤清理。
    """
    b = ROOT / "resources" / "bundles"
    painting = painting.lower()
    paths: list[Path] = []
    if stype == "spine" and painting.startswith("cutscene_"):
        char_id = painting[len("cutscene_"):].replace("char", "")
        paths += [p for p in b.glob(f"isolated-cutscene{char_id}-group*") if p.exists()]
    return [p for p in paths if p.exists()]


def cleanup_processed_bundles() -> dict:
    """关闭软件时自动清理「已提取完成」皮肤的原始下载包（bundle）。

    下载包只在 下载→提取 阶段使用；提取产物（resources/extracted）才是
    预览/导出/应用的数据源，删除下载包不影响任何已提取皮肤。
    遍历 local_skins.json（提取成功的事实来源，build_local_index 只收录
    产物存在的皮肤）逐个删除其 bundle；未提取/提取失败的 bundle 不在索引里，
    自然保留，方便下次重试。同 painting 多类型（如 DOA 联动的 spine+static
    双条目）按各自 type 分别清理，不会漏。
    共享资源不删：bundles/common-interactionvoice_*（全角色共享互动语音大包）。
    受配置 clean_bundles_on_exit 控制，可在设置页关闭。
    """
    if not config.get("clean_bundles_on_exit", True):
        return {"ok": True, "skipped": True, "removed": [], "kept": 0}
    removed: list[str] = []
    for loc in metadata.local_skins():
        stype = loc.get("type", "")
        painting = (loc.get("painting") or "").lower()
        if not painting or stype not in ("spine", "static"):
            continue
        for p in _bundle_paths(stype, painting):
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                removed.append(str(p))
            except Exception as e:  # noqa: BLE001
                print(f"[cleanup] 删除失败 {p}: {e}")
    if removed:
        print(f"[cleanup] 退出清理：删除 {len(removed)} 个已提取皮肤的下载包（保留提取产物）", flush=True)
    return {"ok": True, "removed": removed, "kept": 0}


def _read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def run_tool(name: str, args: list[str] | None = None, timeout: int = 600) -> tuple[int, bytes, bytes]:
    """进程内运行 tools/ 下的脚本模块（打包后无法再用 sys.executable 起子进程）。

    tools 模块没有 __init__.py，按文件路径动态加载，避免引入包结构改动。
    """
    with _TOOL_LOCK:
        import contextlib
        import importlib.util
        import io

        path = ROOT / "tools" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_pack_tool_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old_argv = sys.argv
        sys.argv = [name] + (args or [])
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = mod.main() or 0
        finally:
            sys.argv = old_argv
        out = buf.getvalue().encode("utf-8", "ignore")
        return rc, out, b""


def finish_metadata_update() -> None:
    """同步完成后重建本地索引并刷新内存元数据/资源库。"""
    _sync_skins_and_index()


def run_metadata_update() -> dict:
    """重建 BD2 元数据：BD2DB 中文名/头像 → 官方 catalog + 社区角色表 → characters/ships/skins → 索引。

    names 步骤联网拉取 browndust2-db.souseha.com 的简体角色名/皮肤名并下载头像；
    失败不阻断其余步骤（回退英文名），但会在结果里标为失败。
    任一步工具抛异常也只标 fail、不冒泡（工具崩了不该让整个接口 500）。
    """
    report: dict = {"ok": True, "steps": {}}
    for step, tool, timeout in (
        ("names", "fetch_bd2_names", 240),
        ("characters", "build_bd2_metadata", 300),
        ("skins", "build_bd2_skins", 60),
    ):
        try:
            rc, out, err = run_tool(tool, timeout=timeout)
            report["steps"][step] = {
                "ok": rc == 0,
                "output": out.decode("utf-8", "ignore")[-3000:],
                "error": err.decode("utf-8", "ignore")[-800:],
            }
        except Exception as e:  # noqa: BLE001
            report["steps"][step] = {
                "ok": False,
                "output": "",
                "error": f"{type(e).__name__}: {e}"[:800],
            }
        if not report["steps"][step]["ok"]:
            report["ok"] = False
    try:
        finish_metadata_update()
    except Exception as e:  # noqa: BLE001
        report["ok"] = False
        report["finalize_error"] = f"{type(e).__name__}: {e}"[:800]
    return report


def local_skin_asset(ship: str, bundle: str, name: str | None = None) -> dict | None:
    hits = [
        loc for loc in metadata.local_skins()
        if loc.get("ship") == ship and loc.get("bundle") == bundle
    ]
    if not hits:
        return None
    if name is None:
        return hits[0].get("asset")
    for loc in hits:
        if loc.get("name") == name:
            return loc.get("asset")
    return hits[0].get("asset") if len(hits) == 1 else None


ALIGN_MAP = {
    "center": 0,
    "left-top": 1,
    "right-top": 2,
    "left-bottom": 3,
    "right-bottom": 4,
}


def _preview_writer():
    """延迟导入壁纸封面写入函数（core.wallpaper 依赖较轻，这里仅为可读性）。"""
    from core.wallpaper import write_preview_from_data_url

    return write_preview_from_data_url


def _export_project(ship: str, bundle: str, name: str | None, options: dict) -> str:
    """生成 WE 壁纸项目，返回项目目录。"""
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        raise ValueError(f"皮肤不存在: {ship}/{bundle}")
    asset = local_skin_asset(ship, bundle, name)
    if not asset:
        raise ValueError("该皮肤尚未下载，请先下载后再导出")
    stype = skin.get("type", "")
    if stype not in ("spine", "static"):
        raise ValueError(f"皮肤类型 {stype} 不支持导出壁纸")
    exporter_id = {"spine": "wallpaper_spine", "static": "wallpaper_static"}[stype]
    exporter = registry.get("exporters", exporter_id)
    if exporter is None:
        raise ValueError("导出插件未注册")
    try:
        import importlib
        import inspect
        mod = inspect.getmodule(exporter.__class__)
        if mod:
            importlib.reload(mod)
            exporter = getattr(mod, exporter.__class__.__name__)()
    except Exception:  # noqa: BLE001
        pass
    opts = options or {}
    try:
        proj = exporter.export(
            {**skin, "asset": asset},
            {
                "root": str(ROOT),
                "bg": opts.get("bg", "monet"),
                "bgColor": opts.get("bgColor"),
                "bgImage": opts.get("bgImage"),
                "hideDefaultBg": bool(opts.get("hideDefaultBg", False)),
                "scale": int(opts.get("scale", 100) or 100),
                "bgScale": int(opts.get("bgScale", 100) or 100),
                "offsetX": int(opts.get("offsetX", 0) or 0),
                "offsetY": int(opts.get("offsetY", 0) or 0),
                "charOffsetX": int(opts.get("charOffsetX", 0) or 0),
                "charOffsetY": int(opts.get("charOffsetY", 0) or 0),
                # 人物旋转（度，正=顺时针）：预览"人物旋转"滑块同值烘进模板
                "rotation": int(opts.get("rotation", 0) or 0),
                # 背景图独立位移（只移背景图，预览 drawBg 同语义）
                "bgOffsetX": int(opts.get("bgOffsetX", 0) or 0),
                "bgOffsetY": int(opts.get("bgOffsetY", 0) or 0),
                "alignment": ALIGN_MAP.get(str(opts.get("alignment", "center")), 0),
                "animation": opts.get("animation", ""),
                "animations": opts.get("animations") or [],
                # 面板开关（前端导出选项透传，预览页勾选的状态同步到 WE 侧默认值）
                "voice": bool(opts.get("voice", True)),
                "intro": bool(opts.get("intro", True)),
                "interact": bool(opts.get("interact", True)),
                # Spine 专属：显示交互区域（预览页打开则 WE 默认也打开）
                "showHitAreas": bool(opts.get("showHitAreas", False)),
                # 多预设（每个预设 = 动画 + 背景 + 构图，WE 里下拉切换）：
                # 原样透传列表，导出器负责清洗/拷图/烘 PRESETS_JSON
                "presets": opts.get("presets") or [],
            },
            str(ROOT / "resources" / "wallpapers"),
        )
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"导出失败: {e}") from e
    # 封面：前端截取的预览帧（预览画布即 16:9 构图）优先写成 preview.jpg，
    # 与用户看到的画面一致。失败则保留导出器生成的兜底预览。
    preview_data = opts.get("previewImage")
    if preview_data:
        try:
            _preview_writer()(Path(proj), str(preview_data))
        except Exception as ex:  # noqa: BLE001
            print(f"[preview] 写入预览封面失败: {ex}", flush=True)
    return proj


def export_skin(ship: str, bundle: str, name: str | None, options: dict) -> dict:
    """生成 WE 壁纸项目并打开所在文件夹（手动拖入 Wallpaper Engine）。"""
    try:
        proj = _export_project(ship, bundle, name, options)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        os.startfile(str(Path(proj)))  # noqa: S606
        opened = True
    except Exception as e:  # noqa: BLE001
        opened = False
        return {
            "ok": True,
            "project": proj,
            "opened": False,
            "error": f"导出成功但打开文件夹失败: {e}",
        }
    return {
        "ok": True,
        "project": proj,
        "opened": opened,
        "message": "导出完成，已打开项目文件夹，请把 index.html 拖入 Wallpaper Engine",
    }


def export_static_image(ship: str, bundle: str, name: str | None = None) -> dict:
    """把静态立绘原图导出为普通图片到 resources/exports/ 并打开文件夹。"""
    skin = resolve_skin(ship, bundle, name)
    if not skin:
        return {"ok": False, "error": f"皮肤不存在: {ship}/{bundle}"}
    if skin.get("type") != "static":
        return {"ok": False, "error": "仅静态立绘支持导出图片"}
    asset = local_skin_asset(ship, bundle, name)
    if not asset:
        return {"ok": False, "error": "该皮肤尚未下载，请先下载"}
    src = ROOT / "resources" / asset["dir"] / asset.get("image", "painting.png")
    if not src.exists():
        return {"ok": False, "error": f"未找到立绘文件: {src}"}
    out_dir = ROOT / "resources" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "".join(ch for ch in f"{ship}_{skin.get('name', '')}" if ch not in '<>:"/\\|?*').rstrip(" .")
    dest = out_dir / f"{name or 'painting'}.png"
    shutil.copy2(src, dest)
    try:
        os.startfile(str(out_dir))  # noqa: S606
        opened = True
    except Exception:  # noqa: BLE001
        opened = False
    return {
        "ok": True,
        "path": str(dest),
        "opened": opened,
        "message": f"图片已导出：{dest.name}",
    }


def export_image_data(
    ship: str, bundle: str, name: str | None, data_url: str, index: int | None = None
) -> dict:
    """把前端截取的当前预览帧（PNG dataURL）保存为图片并打开文件夹。

    index 为动画序号（spine 导出时传入）：文件名用"角色名-序号"（如 企业-3.png），
    便于按动画归档截图；不传时保持"角色名_皮肤名.png"的旧命名。
    """
    import base64

    if not data_url or "," not in data_url:
        return {"ok": False, "error": "缺少图像数据"}
    try:
        png = base64.b64decode(data_url.split(",", 1)[1])
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "图像数据解析失败"}
    if not png.startswith(b"\x89PNG"):
        return {"ok": False, "error": "仅支持 PNG 截图"}
    out_dir = ROOT / "resources" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    if index:
        safe_ship = "".join(ch for ch in ship if ch not in '<>:"/\\|?*').rstrip(" .")
        clean = f"{safe_ship or 'ship'}-{int(index)}"
    else:
        clean = "".join(ch for ch in f"{ship}_{name or bundle}" if ch not in '<>:"/\\|?*').rstrip(" .")
    dest = out_dir / f"{clean or 'capture'}.png"
    dest.write_bytes(png)
    try:
        os.startfile(str(out_dir))  # noqa: S606
        opened = True
    except Exception:  # noqa: BLE001
        opened = False
    return {"ok": True, "path": str(dest), "opened": opened, "message": f"图片已导出：{dest.name}"}


def _cleanup_stale_exports(keep: str) -> int:
    """清理 resources/wallpapers 下与本次导出同角色同皮肤的旧项目目录。

    每次「导出并应用」成功后，删除同名壁纸（目录名同前缀 {ship}_{name}_）的
    旧导出——resources/wallpapers 是待应用的中转区，同壁纸只留最新一份即可；
    不同名壁纸（其他角色/皮肤）全部保留。keep 为本次项目路径（绝对或相对均可）。

    目录名格式：{ship}_{name}_{uuid8}，前缀 = 去掉末尾 _{uuid8} 的部分。
    """
    wp = ROOT / "resources" / "wallpapers"
    if not wp.is_dir():
        return 0
    keep_path = Path(keep).resolve()
    keep_name = keep_path.name
    prefix = re.sub(r"_[0-9a-f]{8}$", "", keep_name)
    removed = 0
    for child in wp.iterdir():
        if not child.is_dir():
            continue
        if child.resolve() == keep_path:
            continue
        # 同角色同皮肤：目录名去掉 _uuid8 后与本次前缀一致；不同名则保留
        if re.sub(r"_[0-9a-f]{8}$", "", child.name) != prefix:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    if removed:
        print(f"[export] 已清理 {removed} 个同皮肤旧导出项目目录", flush=True)
    return removed


def apply_skin(ship: str, bundle: str, name: str | None, options: dict) -> dict:
    """导出并直接应用到 Wallpaper Engine（新副本 + openWallpaper，绕开编辑器导入路径）。"""
    try:
        proj = _export_project(ship, bundle, name, options)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    ok = apply_wallpaper(Path(proj))
    if not ok:
        return {
            "ok": False,
            "project": proj,
            "error": "应用失败：未找到 Wallpaper Engine 安装目录",
        }
    # 应用成功才清理旧导出（失败时保留旧导出，用户可能手动拖入本次项目）
    cleaned = _cleanup_stale_exports(proj)
    return {
        "ok": True,
        "project": proj,
        "cleaned": cleaned,
        "message": "已生成并应用壁纸，可在 Wallpaper Engine 中查看",
    }


def download_skin(skin: dict, cancel_event: threading.Event | None = None) -> dict:
    """BD2：下载皮肤资源 → 提取 → 重建索引 → 刷新资源库。

    资源模型与碧蓝完全不同：
    - 主立绘(charXXXXXX)/约会(illust_datingN)/尊爵(specialillustN) 存放在
      **全角色共享大包**（86MB/434MB/438MB，差分下载一次永久复用），
      提取时按关键词过滤出本皮肤的文件；
    - 演出(cutscene_charXXXXXX) 是每角色独立小包，按需解析下载；
    - 静态立绘(illust_charXXXXXX_NNN) 在 UI 贴图包里，按资产键精确定位。
    """
    if skin["type"] not in ("spine", "static"):
        return {"ok": False, "error": f"未知皮肤类型：{skin['type']}"}

    def cancelled() -> dict:
        return {
            "ok": False,
            "cancelled": True,
            "skin": skin,
            "downloaded": downloaded,
            "error": "下载已取消",
        }

    stype = skin["type"]
    painting = (skin.get("painting") or "").lower()
    bundles_dir = ROOT / "resources" / "bundles"
    extracted_dir = ROOT / "resources" / "extracted"
    downloaded = []
    quality = config.get("bd2_quality") or "HD"
    info = cdn.handshake(quality=quality)

    def _download_all(targets: dict[str, int]) -> None:
        for bundle_key, size in targets.items():
            if cancel_event is not None and cancel_event.is_set():
                return
            dest = bundles_dir / bundle_key
            _emit_stage("正在下载", detail=bundle_key)
            ok = cdn.download_asset(info, bundle_key, dest, size, cancel_event=cancel_event)
            downloaded.append({"path": bundle_key, "ok": ok})

    def _resolve(patterns: list) -> dict[str, int]:
        try:
            return cdn.resolve_bundles(info, patterns)
        except Exception as e:  # noqa: BLE001
            logger.exception("catalog 解析失败")
            raise RuntimeError(f"资源目录解析失败: {e}") from e

    if stype == "static":
        # 静态立绘：Illust_1/illust_charXXXXXX_NNN.png 按资产键精确定位
        _emit_stage("正在定位静态立绘", detail=painting)
        targets = _resolve([re.compile(rf"^Illust_1/{re.escape(painting)}\.png$", re.I)])
        if not targets:
            return {"ok": False, "skin": skin, "downloaded": [],
                    "error": f"CDN 目录中未找到静态立绘: {painting}"}
        _download_all(targets)
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        _emit_stage("正在提取静态立绘", detail=painting)
        for bundle_key, ok in ((d["path"], d["ok"]) for d in downloaded):
            src = bundles_dir / bundle_key
            if ok and src.exists():
                try:
                    registry.get("extractors", "static").extract(
                        str(src), painting, str(extracted_dir / "static" / painting)
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[download] {painting} 静态提取失败: {e}")
    else:
        # spine 四族：主立绘 / 约会 / 尊爵 / 演出
        if painting.startswith("illust_dating"):
            # 2026-10 起多章节约会皮按骨架拆分（illust_dating22_1/_2）：CDN 定位
            # 与提取关键词都用基础名（分卷共享同一 prefab 与共享大包），落盘后
            # _split_dating_parts 再按骨架前缀拆到独立目录。
            dating_base = re.sub(r"_(\d+)$", r"", painting)
            _emit_stage("正在定位约会立绘资源包", detail=painting)
            targets = _resolve([re.compile(rf"^Char/Datingillust/{re.escape(dating_base)}\.prefab$", re.I)])
            keywords = [dating_base]
        elif painting.startswith("cutscene_"):
            _emit_stage("正在定位 Ultimate 演出资源包", detail=painting)
            targets = _resolve([re.compile(rf"^SkeletonData/{re.escape(painting)}/", re.I)])
            keywords = None  # 独立小包全量提取
        elif painting.startswith("specialillust"):
            _emit_stage("正在定位尊爵立绘资源包", detail=painting)
            targets = _resolve([re.compile(rf"IllustSpecial/{re.escape(painting)}\.prefab$", re.I)])
            keywords = [painting]
        else:
            _emit_stage("正在定位主立绘资源包", detail=painting)
            targets = _resolve([re.compile(rf"^UI/Prefabs/Spine/IllustSpine/illust_{re.escape(painting)}_", re.I)])
            keywords = [painting]
        if not targets:
            return {"ok": False, "skin": skin, "downloaded": [],
                    "error": f"CDN 目录中未找到资源: {painting}"}
        _download_all(targets)
        if cancel_event is not None and cancel_event.is_set():
            return cancelled()
        _emit_stage("正在提取 Spine 骨架", detail=painting)
        for d in downloaded:
            src = bundles_dir / d["path"]
            if d["ok"] and src.exists():
                try:
                    registry.get("extractors", "spine").extract(
                        str(src), str(extracted_dir / "spine" / painting), keywords=keywords
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[download] {painting} 提取失败: {e}")

        # 互动语音：主立绘直接下载；约会立绘反查所属服装的语音包。
        # （BD2 互动语音按服装挂载，约会皮肤交互也播所属服装的 Int_{Mood} 语音；
        #   分卷 painting（illust_dating22_1）归属同一服装）
        voice_painting = painting
        if not re.fullmatch(r"char\d{6}", painting):
            dating_key = re.sub(r"_(\d+)$", r"", painting)
            for e in metadata.characters():
                if (e.get("dating") or "").lower() == dating_key:
                    voice_painting = f"char{e['id']}"
                    break
        if config.get("voice_download") and re.fullmatch(r"char\d{6}", voice_painting):
            try:
                vt = _resolve([re.compile(rf"interaction_{re.escape(voice_painting)}", re.I)])
                if vt:
                    _emit_stage("正在下载互动语音", detail=voice_painting)
                    _download_all(vt)
                    for d in downloaded:
                        src = bundles_dir / d["path"]
                        if d["ok"] and src.exists():
                            registry.get("extractors", "spine").extract(
                                str(src), str(extracted_dir / "voice" / voice_painting)
                            )
            except Exception as e:  # noqa: BLE001
                print(f"[voice] 语音包下载失败: {e}")

    # 重建本地索引并刷新资源库
    _emit_stage("正在同步本地索引")
    _sync_skins_and_index()
    ok_items = [d for d in downloaded if d["ok"]]
    failed_items = [d for d in downloaded if not d["ok"]]
    if not downloaded:
        return {
            "ok": False,
            "skin": skin,
            "downloaded": downloaded,
            "error": "CDN 清单中未找到资源: " + ", ".join(paintings),
        }
    result: dict = {"ok": not failed_items, "skin": skin, "downloaded": downloaded}
    if failed_items:
        result["error"] = f"部分资源下载失败: {len(failed_items)} 个"
    return result


def voice_status(painting: str) -> dict:
    """查询某服装的互动语音状态：id、是否已解码、cue 列表与互动动作 pick。"""
    try:
        from core import voice as voice_mod
        vid = voice_mod.resolve_id(painting)
        if not vid:
            return {"ok": True, "shipId": None, "has": False, "cues": []}
        cues = voice_mod.voice_cues(vid)
        if not cues:
            # bytes 已下载但未解码：即时补解码
            voice_mod.ensure_decoded(vid)
            cues = voice_mod.voice_cues(vid)
        return {
            "ok": True,
            "shipId": vid,
            "has": bool(cues),
            "cues": cues,
            "pick": {
                b: voice_mod.pick_cue(vid, b)
                for b in ("touch_head", "touch_1", "touch_2", "login", "home")
            },
            "words": voice_mod.words_for(painting),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120], "has": False, "cues": []}


def voice_clean(all_: bool = False) -> dict:
    """清理解码语音。默认只保留「仍有已下载主立绘」的服装；all=True 全部删除。"""
    from core import voice as voice_mod
    if all_:
        return {"ok": True, **voice_mod.clean_voice()}
    try:
        downloaded = downloaded_with_painting()
    except Exception:  # noqa: BLE001
        downloaded = []
    keep: set[str] = set()
    for s in downloaded:
        p = (s.get("painting") or "").lower()
        if re.fullmatch(r"char\d{6}", p):
            keep.add(p)
    return {"ok": True, **voice_mod.clean_voice(keep)}


def voice_backfill() -> dict:
    """为已下载皮肤补齐互动语音（缺 bytes 的通过 CDN 下载）。

    约会立绘（illust_datingN）反查所属服装 id 后一并补齐——约会皮肤的
    互动交互播的就是所属服装的 Int_{Mood} 语音。
    """
    from core import voice as voice_mod
    try:
        downloaded = downloaded_with_painting()
    except Exception:  # noqa: BLE001
        downloaded = []
    targets: list[str] = []
    seen: set[str] = set()
    for s in downloaded:
        p = (s.get("painting") or "").lower()
        if re.fullmatch(r"char\d{6}", p):
            if p not in seen:
                seen.add(p)
                targets.append(p)
            continue
        # 间接 painting（约会立绘等）→ 所属服装
        vid = voice_mod.resolve_id(p)
        if vid and vid not in seen:
            seen.add(vid)
            targets.append(vid)
    ok_ids, skipped = [], 0
    info = cdn.handshake(quality=config.get("bd2_quality") or "HD")
    total = len(targets)
    for i, p in enumerate(targets, 1):
        if voice_mod.voice_cues(p):
            skipped += 1
            continue
        _emit_stage("正在下载语音", detail=p, progress=f"{i}/{total}")
        # bytes 缺失时走一次完整下载（复用 download_skin 的语音分支）
        skin = {"ship": "", "name": "", "painting": p, "bundle": p, "type": "spine"}
        try:
            download_skin(skin)
        except Exception as e:  # noqa: BLE001
            print(f"[voice] {p} 语音补齐失败: {e}")
            continue
        if voice_mod.ensure_decoded(p, emit=lambda s_, d_="", **_: _emit_stage(s_, detail=d_)):
            ok_ids.append(p)
    return {"ok": True, "downloaded": len(ok_ids), "skipped": skipped, "ships": ok_ids}


def open_wallpapers_dir() -> dict:
    """打开软件自己的壁纸输出目录（resources/wallpapers，存放导出的待用壁纸项目）。"""
    d = ROOT / "resources" / "wallpapers"
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(str(d))  # noqa: S606
    return {"ok": True, "path": str(d)}


def clean_exports() -> dict:
    """清理导出的壁纸项目与截图（resources/wallpapers + resources/exports）。"""
    removed = []
    for sub in ("wallpapers", "exports"):
        d = ROOT / "resources" / sub
        if d.is_dir():
            for child in d.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
    return {"ok": True, "removed": len(removed)}


class Handler(BaseHTTPRequestHandler):
    def _query(self, key: str, default: str = "") -> str:
        """解析查询串 ?key=value。"""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        for part in qs.split("&"):
            k, _, v = part.partition("=")
            if k == key:
                return v
        return default

    def _send(self, status: int, payload: dict) -> None:
        # 诊断日志：记录前端每次 API 调用的请求与响应（真实窗口排障用）
        try:
            print(
                f"[api] {self.command} {self.path} -> {status} "
                f"{json.dumps(payload, ensure_ascii=False)[:300]}",
                flush=True,
            )
        except Exception:  # noqa: BLE001
            pass
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self) -> None:
        """SSE 长连接：把下载/提取/同步等阶段事件推送给前端。"""
        q: queue.Queue = queue.Queue(maxsize=200)
        with _EVENT_LOCK:
            _EVENT_QUEUES.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=30)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # 心跳保活
                    self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _EVENT_LOCK:
                if q in _EVENT_QUEUES:
                    _EVENT_QUEUES.remove(q)

    def _is_local_request(self) -> bool:
        """只允许本机页面调用后端：Host 必须为本机地址，且 Origin（浏览器跨站请求必带）
        若存在也必须是本机。这样即使网页被浏览器打开的其他恶意网站请求，也会被拒绝，
        避免恶意网页借本机 API 删除下载/触发下载占满磁盘。"""
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return False
        origin = self.headers.get("Origin") or ""
        if not origin:
            return True  # 同源请求 / 非浏览器客户端（curl、pywebview 等）
        from urllib.parse import urlparse

        return (urlparse(origin).hostname or "").lower() in ("127.0.0.1", "localhost", "::1")

    def _guard_local(self) -> bool:
        """非本机请求时直接返回 403，返回 False 表示调用方应停止处理。"""
        if self._is_local_request():
            return True
        self._send(403, {"ok": False, "error": "forbidden: 仅允许本机调用"})
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        self._send(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        try:
            ensure_fresh_metadata()
            if self.path.startswith("/api/events"):
                self._stream_events()
                return
            if self.path.startswith("/api/health"):            self._send(200, {"ok": True, "plugins": registry.summary()})
            elif self.path.startswith("/api/library/downloaded"):
                self._send(200, {"ok": True, "skins": downloaded_with_painting()})
            elif self.path.startswith("/api/voice/status"):
                self._send(200, voice_status(self._query("painting", "")))
            elif self.path.startswith("/api/backgrounds"):
                ship = urllib.parse.unquote(self._query("ship", ""))
                dirs = background_dirs(ROOT)
                bgs = get_available_backgrounds(dirs.official, dirs.input)
                fn_set = {b["filename"] for b in bgs}
                recs = get_recommendations_for_ship(ship, fn_set) if ship else []
                self._send(200, {
                    "ok": True,
                    "backgrounds": bgs,
                    "categories": CATEGORIES,
                    "recommendations": recs,
                    "upscaleAlgorithms": UPSCALE_ALGORITHMS,
                    "customCount": sum(1 for b in bgs if b.get("source") == "custom"),
                    # 扩图工作流目录：output = 导出待扩图，input = 放扩图成品（导入只扫 input）
                    "outputDir": str(dirs.output),
                    "inputDir": str(dirs.input),
                })
            elif self.path.startswith("/api/config"):
                self._send(200, get_config())
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception:  # noqa: BLE001
            logger.exception("GET %s failed", self.path)
            try:
                self._send(500, {"ok": False, "error": "internal error"})
            except Exception:  # noqa: BLE001
                pass

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard_local():
            return
        try:
            ensure_fresh_metadata()
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path.startswith("/api/"):
                print(
                    f"[api] POST {self.path} body={json.dumps(data, ensure_ascii=False)[:200]}",
                    flush=True,
                )
            if self.path.startswith("/api/download/cancel"):
                cancel_download(data.get("download_id") or "")
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/download"):
                ship = data.get("ship")
                bundle = data.get("bundle")
                name = data.get("name")
                download_id = data.get("download_id") or ""
                skin = resolve_skin(ship, bundle, name)
                if not skin:
                    self._send(404, {"ok": False, "error": f"皮肤不存在: {ship}/{bundle}"})
                    return
                cancel_event = _register_cancel(download_id) if download_id else None
                try:
                    result = download_skin(skin, cancel_event)
                finally:
                    if download_id:
                        _unregister_cancel(download_id)
                self._send(200, result)
            elif self.path.startswith("/api/library/delete"):
                self._send(
                    200,
                    delete_skin_files(
                        data.get("ship"), data.get("bundle"), data.get("name")
                    ),
                )
            elif self.path.startswith("/api/library/delete-batch"):
                # 批量删除：items=[{ship,bundle,name},...]，只重建一次索引（快）
                items = data.get("items") or []
                if not isinstance(items, list) or not items:
                    self._send(400, {"ok": False, "error": "items 为空"})
                else:
                    self._send(200, delete_skins_batch(items))
            elif self.path.startswith("/api/library/cleanup-bundles"):
                self._send(200, cleanup_processed_bundles())
            elif self.path.startswith("/api/library/clear"):
                self._send(200, clear_all_downloads())
            elif self.path.startswith("/api/metadata/update"):
                self._send(200, run_metadata_update())
            elif self.path.startswith("/api/config"):
                self._send(200, set_config(data.get("config") or {}))
            elif self.path.startswith("/api/voice/backfill"):
                self._send(200, voice_backfill())
            elif self.path.startswith("/api/voice/clean"):
                self._send(200, voice_clean(all_=bool(data.get("all"))))
            elif self.path.startswith("/api/log"):
                # 前端运行时错误上报（排障用）：打印到 stdout，不落盘
                print(f"[fe-error] {json.dumps(data, ensure_ascii=False)[:800]}", flush=True)
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/export-image-data"):
                self._send(
                    200,
                    export_image_data(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("dataUrl") or "",
                        index=data.get("index"),
                    ),
                )
            elif self.path.startswith("/api/export-image"):
                self._send(
                    200,
                    export_static_image(data.get("ship"), data.get("bundle"), data.get("name")),
                )
            elif self.path.startswith("/api/export"):
                self._send(
                    200,
                    export_skin(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("options") or {},
                    ),
                )
            elif self.path.startswith("/api/apply"):
                self._send(
                    200,
                    apply_skin(
                        data.get("ship"),
                        data.get("bundle"),
                        data.get("name"),
                        data.get("options") or {},
                    ),
                )
            elif self.path.startswith("/api/palette"):
                ship = data.get("ship")
                bundle = data.get("bundle")
                name = data.get("name")
                mode = data.get("mode") or "auto"
                bg_color = data.get("bgColor")
                skin = resolve_skin(ship, bundle, name)
                asset = local_skin_asset(ship, bundle, name)
                if not skin or not asset:
                    self._send(200, {"ok": False, "error": "皮肤不存在或未下载"})
                else:
                    src = find_palette_source({**skin, "asset": asset}, ROOT)
                    palette = extract_palette(src) if src else None
                    css = mode_css(mode, palette, solid_color=bg_color)
                    self._send(
                        200,
                        {
                            "ok": bool(palette),
                            "colors": palette or fallback_palette(),
                            "source": str(src) if src else None,
                            "css": css,
                        },
                    )
            elif self.path.startswith("/api/backgrounds/export-outpaint"):
                # 扩图工作流第一步：把当前所选背景（含超分版本）复制到扩图中转目录。
                # dir=当前皮肤 asset.dir：同角色姊妹皮肤可能同名不同图，必须按皮肤目录优先解析
                try:
                    self._send(
                        200,
                        export_background_for_outpaint(
                            ROOT, data.get("filename") or "", data.get("dir") or ""),
                    )
                except Exception as ex:  # noqa: BLE001
                    logger.exception("导出扩图背景失败: %s", data.get("filename"))
                    self._send(200, {"ok": False, "error": str(ex)})
            elif self.path.startswith("/api/backgrounds/import-outpaint"):
                # 扩图工作流第三步：把中转目录里的扩图成果导入自定义背景库
                self._send(200, import_outpaint_results(ROOT))
            elif self.path.startswith("/api/backgrounds/delete-custom"):
                self._send(200, delete_custom_background(ROOT, data.get("filename") or ""))
            elif self.path.startswith("/api/backgrounds/upscale"):
                filename = data.get("filename") or ""
                scale = int(data.get("scale") or 2)
                algo = data.get("algorithm") or "waifu2x"
                denoise = int(data.get("denoise") or 0)
                tta = bool(data.get("tta", False))
                downsample = bool(data.get("downsample", False))
                try:
                    res = upscale_background_image(
                        filename,
                        scale=scale,
                        algorithm=algo,
                        denoise=denoise,
                        tta=tta,
                        downsample=downsample,
                    )
                    self._send(200, res)
                except Exception as ex:  # noqa: BLE001
                    logger.exception("超分背景图片失败: %s", filename)
                    self._send(200, {"ok": False, "error": str(ex)})
            elif self.path.startswith("/api/open/output-dir"):
                dirs = background_dirs(ROOT)
                dirs.output.mkdir(parents=True, exist_ok=True)
                os.startfile(str(dirs.output))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/input-dir"):
                dirs = background_dirs(ROOT)
                dirs.input.mkdir(parents=True, exist_ok=True)
                os.startfile(str(dirs.input))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/custom-dir"):
                # 兼容旧前端：成品库已并入 input，这里打开同一个目录
                dirs = background_dirs(ROOT)
                dirs.input.mkdir(parents=True, exist_ok=True)
                os.startfile(str(dirs.input))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/background-dir"):
                dirs = background_dirs(ROOT)
                dirs.official.mkdir(parents=True, exist_ok=True)
                os.startfile(str(dirs.official))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/download-dir"):
                os.startfile(str(ROOT / "resources" / "bundles"))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/extracted-dir"):
                os.startfile(str(ROOT / "resources" / "extracted"))  # noqa: S606
                self._send(200, {"ok": True})
            elif self.path.startswith("/api/open/wallpapers-dir"):
                self._send(200, open_wallpapers_dir())
            elif self.path.startswith("/api/library/clean-exports"):
                self._send(200, clean_exports())
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as e:  # noqa: BLE001
            logger.exception("POST %s failed", self.path)
            self._send(500, {"ok": False, "error": str(e)})

    def log_message(self, *args) -> None:  # noqa: D401
        pass


def main(port: int = 8766) -> None:
    """启动后端 API 服务。

    注意：打包版/桌面版会以线程方式调用 main(8770) 传入端口，
    因此这里**不再**从 sys.argv 读端口（之前会被启动参数意外覆盖，
    导致前端连不上后端）。
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"backend API listening on http://127.0.0.1:{port}")
    logger.info("backend API listening on http://127.0.0.1:%s", port)
    server.serve_forever()


if __name__ == "__main__":
    _port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    main(_port)
