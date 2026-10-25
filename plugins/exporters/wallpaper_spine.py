"""Spine 壁纸导出插件：生成 WE web 壁纸项目（base64 内嵌骨架 + 多贴图）。"""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path

from core.registry import ExporterPlugin
from core.wallpaper import (
    BD2_INTERACT,
    SPINE_RUNTIME,
    WALLPAPER_LAYOUT,
    bg_css_for_skin,
    export_defaults,
    generate_preview_image,
    project_dir_name,
    project_json,
    render_template,
)


class WallpaperSpineExporter(ExporterPlugin):
    id = "wallpaper_spine"
    name = "Spine 壁纸导出"

    def export(self, skin: dict, options: dict, out_dir: str) -> str:
        out = Path(out_dir)
        proj = out / project_dir_name(skin["ship"], skin["name"])
        assets = proj / "assets"
        assets.mkdir(parents=True, exist_ok=True)

        src_dir = Path(options["root"]) / "resources" / skin["asset"]["dir"]
        shutil.copy2(SPINE_RUNTIME, proj / "spine-webgl-4.1.js")
        shutil.copy2(WALLPAPER_LAYOUT, proj / "wallpaper-layout.js")
        # BD2 互动引擎（单源共享文件，与预览端同一份）
        shutil.copy2(BD2_INTERACT, proj / "bd2-interact.js")

        # 多预设（动画 + 背景 + 构图，WE 下拉切换）：清洗 + 每预设拷背景图/算 CSS。
        # 有预设时主占位值（SCALE/OFFSET/ANIMATION/BG_CSS/HIDE_DEFAULT_BG…）取
        # 首个预设，保证不碰 WE 属性时壁纸就是预设 1 的状态。
        wp_presets = _sanitize_presets(options.get("presets"))
        base_opts = dict(options)
        if wp_presets:
            p0 = wp_presets[0]
            base_opts.update({
                "bg": p0["bg"], "bgColor": p0["bgColor"], "bgImage": p0["bgImage"],
                "hideDefaultBg": p0["hideDefaultBg"],
                "scale": p0["scale"], "offsetX": p0["offsetX"], "offsetY": p0["offsetY"],
                "charOffsetX": p0["charOffsetX"], "charOffsetY": p0["charOffsetY"],
                "rotation": p0["rotation"],
                "bgScale": p0["bgScale"], "bgOffsetX": p0["bgOffsetX"], "bgOffsetY": p0["bgOffsetY"],
                "animation": p0["animation"],
            })

        layers = []
        bg_images = []
        bg_sets = []
        skel_sets = skin["asset"].get("skel_sets") or {}
        has_login = False
        # 全部阶段背景（bg_sets，Ultimate 每阶段一组）：拷贝并按组注入，模板运行时
        # 随当前动画切换显示（bgImages 仍是默认第一组，供单组/兼容路径）。
        # 若用户启用了自定义扩图/外部背景/非 auto 背景样式，则不注入骨架内置默认背景，避免重叠出现两个背景
        custom_bg_active = (
            bool(base_opts.get("hideDefaultBg"))
            or base_opts.get("bg") != "auto"
            or bool(base_opts.get("bgImage"))
        )
        # 预设里只要有一个 auto（官方背景），内置背景组必须带上
        presets_need_default = bool(wp_presets) and any(p["bg"] == "auto" for p in wp_presets)
        if not custom_bg_active or presets_need_default:
            for set_no in sorted((skin["asset"].get("bg_sets") or {}), key=lambda k: int(k) if str(k).isdigit() else 0):
                fname = skin["asset"]["bg_sets"][set_no]
                shutil.copy2(src_dir / fname, assets / fname)
                bg_sets.append({"set": int(set_no) if str(set_no).isdigit() else 0, "file": "assets/" + fname})
        for layer in skin["asset"]["layers"]:
            if "bg" in layer:
                if not custom_bg_active or presets_need_default:
                    # cutscene 独立背景图：复制进壁纸，由模板 BG_IMAGES 渲染在角色后面
                    shutil.copy2(src_dir / layer["bg"], assets / layer["bg"])
                    bg_images.append({"file": "assets/" + layer["bg"]})
                continue
            if custom_bg_active and not presets_need_default and re.search(r"b(?:g)?\d*$", layer["skel"].replace(".skel", ""), re.I):
                # 启用了自定义/扩图背景时，跳过骨架内置背景层（预设含 auto 时不跳）
                continue
            skel = (src_dir / layer["skel"]).read_bytes()
            # 自动检测 login 动画：直接在 skel 二进制里搜动画名字符串
            # （比运行时解析轻量；碧蓝 skel 动画名以可读 ASCII 存储）
            if b"login" in skel:
                has_login = True
            atlas_text = (src_dir / layer["atlas"]).read_text(encoding="utf-8")
            pages = re.findall(r"^([^\r\n]+\.png)\s*$", atlas_text, re.M)
            textures = []
            for page in pages:
                shutil.copy2(src_dir / page, assets / page)
                textures.append({"page": page, "file": "assets/" + page})
            layers.append({
                "name": layer["skel"].replace(".skel", ""),
                "skelData": base64.b64encode(skel).decode("ascii"),
                "atlasText": atlas_text,
                "textures": textures,
            })

        # 互动语音：开关开启且本地有该船语音时复制进壁纸并注入运行时配置
        voice_on = bool(options.get("voice", True))
        voice_cfg = None
        if voice_on:
            try:
                from core import voice as voice_mod
                # resolve_id：约会立绘(illust_datingN)反查所属服装的语音包
                ship_id = voice_mod.resolve_id(skin.get("painting", ""))
                if ship_id:
                    voice_cfg = voice_mod.export_voice(ship_id, proj / "assets" / "voice")
            except Exception:  # noqa: BLE001
                voice_cfg = None

        # 开场动画：仅皮肤有 login 动画时提供（自动检测）；关闭时不播入场直接待机
        intro_on = bool(options.get("intro", True)) and has_login
        # 互动开关（点击/拖拽触发动画反应）
        interact_on = bool(options.get("interact", True))

        # 交互区域/点击规则占位：BD2 拟官方互动由 bd2-interact.js 在运行时接管
        # （预览与壁纸同源引擎），此 JSON 仅保留碧蓝模板接口兼容。
        hit_areas = []
        interact_rules = []

        # 背景图导出：官方(background) / 扩图导入(custom) / 临时超分(preview) 三处统一解析
        bg_image_opt = base_opts.get("bgImage")
        bg_img_css_ref = None
        if base_opts.get("bg") == "image" and bg_image_opt:
            from core.backgrounds import resolve_background_file
            bg_file = resolve_background_file(base_opts["root"], bg_image_opt)
            if bg_file is not None:
                shutil.copy2(bg_file, assets / bg_file.name)
                bg_img_css_ref = f"assets/{bg_file.name}"

        # 多预设：每预设拷自己的背景图（image 模式）并算 CSS；同名不同源时加序号防覆盖
        from core.backgrounds import resolve_background_file as _rbf
        _copied_bgs: dict[str, str] = {}  # 源路径 → assets 相对名
        for p in wp_presets:
            p_ref = None
            if p["bg"] == "image" and p["bgImage"]:
                src_bg = _rbf(base_opts["root"], p["bgImage"])
                if src_bg is not None:
                    key = str(src_bg)
                    if key in _copied_bgs:
                        p_ref = _copied_bgs[key]
                    else:
                        dest_name = src_bg.name
                        if (assets / dest_name).exists() and (assets / dest_name).read_bytes()[:64] != src_bg.read_bytes()[:64]:
                            stem, suf = dest_name.rsplit(".", 1) if "." in dest_name else (dest_name, "png")
                            dest_name = f"{stem}_{len(_copied_bgs) + 1}.{suf}"
                        shutil.copy2(src_bg, assets / dest_name)
                        p_ref = f"assets/{dest_name}"
                        _copied_bgs[key] = p_ref
            p["bgImageRef"] = p_ref
            p["bgCss"] = bg_css_for_skin(
                skin,
                base_opts["root"],
                p["bg"],
                p["bgColor"],
                bg_image=p_ref,
                bg_scale=p["bgScale"],
                bg_offset_x=p["bgOffsetX"],
                bg_offset_y=p["bgOffsetY"],
                offset_x=p["offsetX"],
                offset_y=p["offsetY"],
            )
        presets_json = json.dumps(
            [
                {
                    "name": p["name"], "animation": p["animation"],
                    "scale": p["scale"], "offsetX": p["offsetX"], "offsetY": p["offsetY"],
                    "charOffsetX": p["charOffsetX"], "charOffsetY": p["charOffsetY"],
                    "rotation": p["rotation"],
                    "bgScale": p["bgScale"], "bgOffsetX": p["bgOffsetX"], "bgOffsetY": p["bgOffsetY"],
                    "bgCss": p["bgCss"], "hideDefaultBg": p["hideDefaultBg"],
                    "bgImage": p["bgImageRef"],
                }
                for p in wp_presets
            ],
            ensure_ascii=False,
        )

        bg_scale = max(30, min(300, int(base_opts.get("bgScale", 100) or 100)))
        html = render_template(
            "wallpaper_spine.html",
            LAYERS_JSON=json.dumps(layers, ensure_ascii=False),
            SKEL_SETS_JSON=json.dumps(skel_sets, ensure_ascii=False),
            BG_IMAGES_JSON=json.dumps(bg_images, ensure_ascii=False),
            BG_SETS_JSON=json.dumps(bg_sets, ensure_ascii=False),
            PRESETS_JSON=presets_json,
            BG_SCALE=str(bg_scale),
            TITLE=f"{skin['ship']} · {skin['name']}",
            BG_CSS=bg_css_for_skin(
                skin,
                base_opts["root"],
                base_opts.get("bg", "monet"),
                base_opts.get("bgColor"),
                bg_image=bg_img_css_ref,
                bg_scale=bg_scale,
                bg_offset_x=int(base_opts.get("bgOffsetX", 0) or 0),
                bg_offset_y=int(base_opts.get("bgOffsetY", 0) or 0),
                offset_x=int(base_opts.get("offsetX", 0) or 0),
                offset_y=int(base_opts.get("offsetY", 0) or 0),
            ),
            VOICE_JSON=json.dumps(voice_cfg, ensure_ascii=False) if voice_cfg else "null",
            VOICE="true" if voice_on else "false",
            INTRO="true" if intro_on else "false",
            INTERACT="true" if interact_on else "false",
            HIDE_DEFAULT_BG="true" if (custom_bg_active and not presets_need_default) else "false",
            HIT_AREAS_JSON=json.dumps(hit_areas, ensure_ascii=False),
            INTERACT_RULES_JSON=json.dumps(interact_rules, ensure_ascii=False),
            **export_defaults(base_opts),
        )
        (proj / "index.html").write_text(html, encoding="utf-8")
        (proj / "project.json").write_text(
            json.dumps(
                project_json(
                    f"{skin['ship']} · {skin['name']}",
                    scale=options.get("scale", 100),
                    offset_x=options.get("offsetX", 0),
                    offset_y=options.get("offsetY", 0),
                    # 角色水平/垂直偏移不再生成 WE 控件（用户需求）：预览调好的值
                    # 以内联 CHAR_OFFSET_X/Y 烘进 index.html，WE 侧不可再调
                    alignment=int(base_opts.get("alignment", 0) or 0),
                    animations=base_opts.get("animations") or [],
                    animation=base_opts.get("animation") or "",
                    voice=voice_on,
                    intro=intro_on,
                    interact=bool(base_opts.get("interact", True)),
                    presets=[p["name"] for p in wp_presets],
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        generate_preview_image(proj, bg_file if bg_img_css_ref else None)
        return str(proj)


def _sanitize_presets(raw) -> list[dict]:
    """清洗前端传来的预设列表：只保留已知键 + 数值夹取，最多 8 个。

    每个预设 = 动画 + 背景（模式/颜色/图片）+ 构图（缩放/偏移/旋转/背景缩放偏移）。
    hideDefaultBg 由 bg 模式推导（auto=官方背景走 WebGL，其余走 CSS 背景）。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []

    def _int(v, lo, hi, dft):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return dft

    for i, item in enumerate(raw[:8]):
        if not isinstance(item, dict):
            continue
        bg = str(item.get("bg") or "auto")
        if bg not in ("auto", "image", "monet", "solid", "frost", "star"):
            bg = "auto"
        name = str(item.get("name") or "").strip()[:24] or f"预设 {i + 1}"
        out.append({
            "name": name,
            "animation": str(item.get("animation") or "")[:64],
            "bg": bg,
            "bgColor": str(item.get("bgColor") or "")[:32] or None,
            "bgImage": str(item.get("bgImage") or "")[:128] or None,
            "hideDefaultBg": bg != "auto",
            "scale": _int(item.get("scale"), 20, 300, 100),
            "offsetX": _int(item.get("offsetX"), -100, 100, 0),
            "offsetY": _int(item.get("offsetY"), -100, 100, 0),
            "charOffsetX": _int(item.get("charOffsetX"), -100, 100, 0),
            "charOffsetY": _int(item.get("charOffsetY"), -100, 100, 0),
            "rotation": _int(item.get("rotation"), -180, 180, 0),
            "bgScale": _int(item.get("bgScale"), 30, 300, 100),
            "bgOffsetX": _int(item.get("bgOffsetX"), -100, 100, 0),
            "bgOffsetY": _int(item.get("bgOffsetY"), -100, 100, 0),
        })
    # 预设名去重（WE combo 按 value 区分）
    seen = set()
    for j, p in enumerate(out):
        base = p["name"]
        n = base
        k = 2
        while n in seen:
            n = f"{base} {k}"
            k += 1
        p["name"] = n
        seen.add(n)
    return out
