# -*- coding: utf-8 -*-
"""棕色尘埃2 场景背景图管理与扩图工作流。

支持：
1. 扫描 resources/background/ 下的官方/外部场景图（如有）；
2. 扩图工作流：
   - resources/output/  导出目录：导出当前所选背景到此，供外部工具（PS 生成式填充 / SD 等）扩图；
   - resources/input/   扩图成品库：扩图成品放进这里即可选用（点「导入扩图」刷新，
     打开背景列表时也会自动可见）。软件【不再复制】文件——删掉 input 里的图片，
     它就从背景列表消失；同名文件覆盖同名官方背景；
   - resources/preview/ 临时超分产物预览目录；
3. 缩略图自动生成 (resources/thumbnails/background/) 与缓存；
4. 旧版 resources/custom/ 持久成品库已废弃：启动时 migrate_legacy_custom() 把其中的
   文件并入 input，之后该目录不再被读取。
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, NamedTuple
from PIL import Image

# 资源目录名（相对 resources/）
BACKGROUND_DIRNAME = "background"
OUTPUT_DIRNAME = "output"
INPUT_DIRNAME = "input"           # 扩图成品库：放进来的图直接可用，删掉即从列表消失
PREVIEW_DIRNAME = "preview"
LEGACY_CUSTOM_DIRNAME = "custom"  # 旧版持久成品库（已废弃，仅用于启动迁移）

# 可作为背景导入/导出的图片扩展名（扩图工具可能输出 jpg/webp/bmp 等）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# 参与超分与壁纸导出的扩展名（超分引擎只吃 png，其余格式导入时统一转 png）
UPSCALABLE_EXTS = {".png"}
# 自定义背景缩略图后缀：与官方同名背景区分，互不覆盖
CUSTOM_THUMB_SUFFIX = "__custom"


class BackgroundDirs(NamedTuple):
    """背景相关目录集合。

    input 既是「放扩图成品的目录」也是背景库本身：前端「自定义 / 扩图」分类列的就是
    它，所以删掉 input 里的文件即从列表移除（软件不再另存一份持久副本）。
    """

    official: Path
    input: Path
    output: Path
    preview: Path
    legacy_custom: Path  # 旧版成品库（已废弃，仅供启动迁移）


def background_dirs(root: Path) -> BackgroundDirs:
    """返回背景相关目录集合（official / input=成品库 / output / preview / legacy custom）。"""
    res = Path(root) / "resources"
    return BackgroundDirs(
        official=res / BACKGROUND_DIRNAME,
        input=res / INPUT_DIRNAME,
        output=res / OUTPUT_DIRNAME,
        preview=res / PREVIEW_DIRNAME,
        legacy_custom=res / LEGACY_CUSTOM_DIRNAME,
    )


CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "custom",
        "name": "自定义 / 扩图",
        "keywords": [],
    },
    {
        "id": "scenery",
        "name": "自然风光 / 城镇",
        "keywords": ["town", "city", "street", "village", "forest", "field", "mountain", "sea", "beach", "sky", "garden", "lake"],
    },
    {
        "id": "indoor",
        "name": "室内 / 设施",
        "keywords": ["room", "house", "bar", "inn", "pub", "palace", "castle", "hall", "shop", "office", "bedroom", "kitchen"],
    },
    {
        "id": "fantasy",
        "name": "奇幻 / 战斗 / 地牢",
        "keywords": ["dungeon", "ruin", "battle", "dark", "magic", "temple", "altar", "cave", "tower"],
    },
]


def _clean_str(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def _friendly_name(filename: str) -> str:
    stem = Path(filename).stem
    # 替换常见连字符与下划线
    name = re.sub(r"[_\-]+", " ", stem).strip()
    return name or filename


def _classify(filename: str) -> str:
    clean = _clean_str(filename)
    for c in CATEGORIES:
        if c["id"] == "custom":
            continue
        if any(_clean_str(kw) in clean for kw in c["keywords"]):
            return c["id"]
    return "scenery"


def _thumb_rel_path(filename: str, source: str = "official") -> str:
    stem = Path(filename).stem
    if source == "custom":
        return f"thumbnails/background/{stem}{CUSTOM_THUMB_SUFFIX}.webp"
    return f"thumbnails/background/{stem}.webp"


def custom_thumb_name(filename: str) -> str:
    """自定义背景缩略图文件名（对外暴露，导入/删除共用）。"""
    return f"{Path(filename).stem}{CUSTOM_THUMB_SUFFIX}.webp"


def resolve_background_file(root: Path, filename: str, source_dir: str = "") -> Path | None:
    """把背景文件名解析为磁盘上的实际文件。

    查找顺序：当前皮肤目录(source_dir 指定时) → 扩图成品库(input) → 官方(background)
    → 角色提取产物(extracted) → 导出目录(output) → 超分预览(preview)。
    只取文件名部分，拒绝任何带路径分隔符的输入（防目录穿越）。

    source_dir（皮肤 asset.dir，如 extracted/spine/cutscene_char003403）必须最优先：
    官方会在别的皮肤包里复用背景文件名（实测 cutscene_char003403「使徒」的背景
    就叫 char003402_back1.png，与同角色「白日梦兔女郎」同名但内容不同），output/
    又会堆积历次导出的同名副本——不带皮肤上下文解析会拿到别的皮肤的图
    （"导出了角色另一个皮肤的背景"，2026-10 实测修复）。input/official 仍是
    用户主动的同名覆盖，优先于皮肤默认。
    """
    name = str(filename or "").replace("\\", "/").strip()
    if not name:
        return None
    name = name.rsplit("/", 1)[-1]
    if not name or name in (".", ".."):
        return None
    root_path = Path(root)

    # 皮肤目录优先：source_dir 限定为 resources/ 下的安全相对路径
    sd = str(source_dir or "").replace("\\", "/").strip().strip("/")
    if sd and ".." not in sd.split("/"):
        cand = (root_path / "resources" / sd / name).resolve()
        try:
            if cand.is_file() and root_path.resolve() in cand.parents:
                return cand
        except OSError:
            pass

    dirs = background_dirs(root_path)
    for directory in (dirs.input, dirs.official):
        p = directory / name
        if p.is_file():
            return p
    # 皮肤提取产物：精确相对路径优先，其次全局同名检索
    ext_dir = root_path / "resources" / "extracted"
    if ext_dir.is_dir():
        direct = ext_dir / name
        if direct.is_file():
            return direct
        for cand in ext_dir.rglob(name):
            if cand.is_file():
                return cand
    for directory in (dirs.output, dirs.preview):
        p = directory / name
        if p.is_file():
            return p
    return None


def ensure_thumbnail(bg_dir: Path, filename: str, thumb_name: str | None = None) -> str:
    """确保指定背景图片的缩略图存在，若不存在自动生成 (320x180 WebP)。"""
    base_stem = Path(filename).stem
    thumb_dir = Path(bg_dir).parent / "thumbnails" / "background"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / (thumb_name or f"{base_stem}.webp")
    if not thumb_path.exists() or thumb_path.stat().st_size == 0:
        src_path = Path(bg_dir) / filename
        if src_path.exists():
            try:
                with Image.open(src_path) as im:
                    im.thumbnail((320, 180), Image.BILINEAR)
                    im.convert("RGB").save(thumb_path, "WEBP", quality=75)
            except Exception:
                return filename
    return thumb_path.name


def get_available_backgrounds(bg_dir: Path, library_dir: Path | None = None) -> list[dict[str, Any]]:
    """扫描扩图成品库(input)与官方背景目录，返回统一格式的背景条目列表。

    每条含 source 字段（"custom"=成品库 / "official"）。source 标签保留 "custom"
    是为了兼容前端（徽标与删除按钮按它判断）；同名时成品库条目覆盖官方条目，
    且不做去重——文件在谁就在列表里，删掉文件即消失。成品库就是 resources/input。
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    pairs: list[tuple[Path | None, str]] = [(library_dir, "custom"), (bg_dir, "official")]
    for directory, source in pairs:
        if not directory or not directory.is_dir():
            continue
        for f in sorted(directory.iterdir()):
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
                continue
            if f.name in seen:
                continue
            seen.add(f.name)
            if source == "custom":
                ensure_thumbnail(directory, f.name, custom_thumb_name(f.name))
                results.append({
                    "filename": f.name,
                    "name": _friendly_name(f.name),
                    "category": "custom",
                    "thumb": _thumb_rel_path(f.name, "custom"),
                    "source": "custom",
                })
            else:
                ensure_thumbnail(directory, f.name)
                results.append({
                    "filename": f.name,
                    "name": _friendly_name(f.name),
                    "category": _classify(f.name),
                    "thumb": _thumb_rel_path(f.name),
                    "source": "official",
                })

    # 自定义置顶，其余按名称排序
    results.sort(key=lambda x: (x["source"] != "custom", x["name"].lower()))
    return results


def _file_digest(path: Path) -> str:
    """文件内容摘要，用于判断扩图成果是否与已导入的一致（避免重复导入）。"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches_official(bg_dir: Path, name: str, candidate: Path) -> bool:
    """中转文件是否与同名官方背景内容一致（即'导出后原样丢回来、还没扩图'）。"""
    official = Path(bg_dir) / name
    if not official.is_file():
        return False
    try:
        return _file_digest(official) == _file_digest(candidate)
    except Exception:  # noqa: BLE001
        return False


def _outpaint_readme() -> str:
    return (
        "扩图工作流说明（本文件夹 = output 导出目录）\r\n"
        "================================================\r\n"
        "1) 在软件里选好背景，点「📤 导出扩图」——当前背景（含已超分版本）会复制到本文件夹；\r\n"
        "2) 用 Photoshop 生成式扩展 / Stable Diffusion 等工具把画面扩到目标比例；\r\n"
        "3) 把做好的成品放进软件资源目录下的 input 文件夹（png/jpg/webp/bmp 均可，\r\n"
        "   文件名随意，非 png 导入时会自动转成 png）；\r\n"
        "4) 回到软件点「📥 导入扩图」——input 里的图片会转入自定义背景库，\r\n"
        "   在「自定义 / 扩图」分类里即可选中、超分、合成、导出壁纸。\r\n"
        "\r\n"
        "注意：只有 input 文件夹里的图片会被导入，本文件夹（output）不会被扫描。\r\n"
    )


def export_background_for_outpaint(root: Path, filename: str, source_dir: str = "") -> dict:
    """把当前所选背景复制到导出目录(output)，供外部工具扩图。

    source_dir 为当前皮肤的 asset.dir——同角色姊妹皮肤可能存在同名不同图的
    背景文件，必须按皮肤目录优先解析（见 resolve_background_file）。
    """
    src = resolve_background_file(root, filename, source_dir)
    if src is None:
        raise FileNotFoundError(f"背景原图不存在：{filename}")

    dirs = background_dirs(root)
    dirs.output.mkdir(parents=True, exist_ok=True)
    dirs.input.mkdir(parents=True, exist_ok=True)

    dest = dirs.output / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)

    readme = dirs.output / "扩图说明.txt"
    if not readme.exists():
        try:
            readme.write_text(_outpaint_readme(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": True,
        "filename": dest.name,
        "source": str(src),
        "dir": str(dirs.output),
        "inputDir": str(dirs.input),
        "message": f"已导出到 output：{dest.name}（扩图完成后把成品放进 input，再点「导入扩图」）",
    }


def import_outpaint_results(root: Path) -> dict:
    """刷新扩图成品库(input)：扫描其中的图片、生成缩略图，返回可选用清单。

    软件【不复制、不转换】文件——input 就是成品库本身：
      - 放进去的图片立即可在「自定义 / 扩图」分类选用；
      - 删掉 input 里的图片，它就从列表消失（不再另存持久副本）；
      - 同名文件覆盖同名官方背景（resolve_background_file 优先命中 input）。
    只扫 input——output 里是待扩图的原始导出，不参与导入。
    """
    dirs = background_dirs(root)
    bg_dir, input_dir = dirs.official, dirs.input
    input_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[str] = []
    unchanged: list[str] = []
    failed: list[str] = []

    for f in sorted(input_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            ensure_thumbnail(input_dir, f.name, custom_thumb_name(f.name))
        except Exception:  # noqa: BLE001
            failed.append(f.name)
            continue
        candidates.append(f.name)
        # 与同名官方背景字节一致 = 导出后原样丢回来（还没扩图），只提示不隐藏
        if _matches_official(bg_dir, f.name, f):
            unchanged.append(f.name)

    if candidates:
        message = f"input 中 {len(candidates)} 张图片已可用于背景选择"
        if unchanged:
            message += f"（其中 {len(unchanged)} 张与官方原图一致，可能还没扩图）"
    else:
        message = "input 里还没有图片：把扩图成品放进 input 即可选用（导出目录 output 不会被扫描）"
    return {
        "ok": True,
        # 前端拿 imported 当「自动识别并应用」的候选，这里就是成品库现有的全部图片
        "imported": candidates,
        "skipped": [],
        "unchanged": unchanged,
        "failed": failed,
        "count": len(candidates),
        "dir": str(input_dir),
        "message": message,
    }


def migrate_legacy_custom(root: Path) -> int:
    """把旧版 resources/custom（持久成品库，已废弃）里的图片并入 input，返回迁移数。

    幂等：custom 不存在或没有图片时是空操作。同名冲突按内容处理——内容一致即同一张
    图（丢弃旧目录里的重复份），内容不同则保留两份（旧文件加 _legacy 后缀），
    绝不静默删掉用户文件。缩略图由后续扫描按需重建。
    """
    dirs = background_dirs(root)
    legacy, library = dirs.legacy_custom, dirs.input
    if not legacy.is_dir():
        return 0
    library.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in sorted(legacy.iterdir()):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
            continue
        dest = library / f.name
        try:
            if dest.exists():
                if _file_digest(dest) == _file_digest(f):
                    f.unlink()
                    moved += 1
                    continue
                dest = library / f"{f.stem}_legacy{f.suffix}"
                if dest.exists():
                    continue
            shutil.move(str(f), str(dest))
            moved += 1
        except Exception:  # noqa: BLE001
            continue
    if moved:
        print(f"[bg] 已把旧 custom 成品库的 {moved} 个文件并入 input", flush=True)
    return moved


def delete_custom_background(root: Path, filename: str) -> dict:
    """从成品库(input)删除一张背景（连同缩略图）；同名官方背景会自动重新可见。"""
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    dirs = background_dirs(root)
    library_dir, official_dir = dirs.input, dirs.official
    target = library_dir / name
    if not name or not target.is_file():
        return {"ok": False, "error": f"背景不存在：{filename}"}

    target.unlink()
    thumb = library_dir.parent / "thumbnails" / "background" / custom_thumb_name(target.name)
    try:
        if thumb.is_file():
            thumb.unlink()
    except Exception:  # noqa: BLE001
        pass

    official = official_dir / name
    if official.is_file():
        try:
            ensure_thumbnail(official_dir, name)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "filename": name, "message": f"已删除自定义背景：{name}"}


def get_recommendations_for_ship(
    ship_name: str,
    available_filenames: set[str],
) -> list[str]:
    """为特定角色推荐背景文件名列表（只返回本地实际存在的背景）。"""
    s_lower = (ship_name or "").lower().strip()

    rec_keys = []
    # 皮肤/角色关键词匹配
    if any(w in s_lower for w in ["summer", "beach", "ocean", "swim", "水着", "泳装", "海", "比基尼"]):
        rec_keys.extend([fn for fn in available_filenames if any(k in fn.lower() for k in ["beach", "sea", "ocean", "summer", "water"])])
    if any(w in s_lower for w in ["winter", "snow", "xmas", "christmas", "温泉", "冬", "雪"]):
        rec_keys.extend([fn for fn in available_filenames if any(k in fn.lower() for k in ["snow", "winter", "ice"])])
    if any(w in s_lower for w in ["maid", "女仆", "新娘", "bride", "宴会", "party"]):
        rec_keys.extend([fn for fn in available_filenames if any(k in fn.lower() for k in ["room", "inn", "bar", "hall", "palace"])])

    # 兜底：如果前述没匹配到，可取前几个背景
    if not rec_keys and available_filenames:
        rec_keys.extend(sorted(available_filenames)[:5])

    final_recs = []
    seen = set()
    for fn in rec_keys:
        if fn in available_filenames and fn not in seen:
            seen.add(fn)
            final_recs.append(fn)

    return final_recs
