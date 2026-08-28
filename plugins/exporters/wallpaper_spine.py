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

        layers = []
        bg_images = []
        has_login = False
        for layer in skin["asset"]["layers"]:
            if "bg" in layer:
                # cutscene 独立背景图：复制进壁纸，由模板 BG_IMAGES 渲染在角色后面
                shutil.copy2(src_dir / layer["bg"], assets / layer["bg"])
                bg_images.append({"file": "assets/" + layer["bg"]})
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

        bg_scale = max(30, min(300, int(options.get("bgScale", 100) or 100)))
        html = render_template(
            "wallpaper_spine.html",
            LAYERS_JSON=json.dumps(layers, ensure_ascii=False),
            BG_IMAGES_JSON=json.dumps(bg_images, ensure_ascii=False),
            BG_SCALE=str(bg_scale),
            TITLE=f"{skin['ship']} · {skin['name']}",
            BG_CSS=bg_css_for_skin(
                skin, options.get("root"), options.get("bg", "monet"), options.get("bgColor")
            ),
            VOICE_JSON=json.dumps(voice_cfg, ensure_ascii=False) if voice_cfg else "null",
            VOICE="true" if voice_on else "false",
            INTRO="true" if intro_on else "false",
            INTERACT="true" if interact_on else "false",
            HIT_AREAS_JSON=json.dumps(hit_areas, ensure_ascii=False),
            INTERACT_RULES_JSON=json.dumps(interact_rules, ensure_ascii=False),
            **export_defaults(options),
        )
        (proj / "index.html").write_text(html, encoding="utf-8")
        (proj / "project.json").write_text(
            json.dumps(
                project_json(
                    f"{skin['ship']} · {skin['name']}",
                    scale=options.get("scale", 100),
                    offset_x=options.get("offsetX", 0),
                    offset_y=options.get("offsetY", 0),
                    alignment=int(options.get("alignment", 0) or 0),
                    animations=options.get("animations") or [],
                    animation=options.get("animation") or "",
                    voice=voice_on,
                    intro=intro_on,
                    interact=bool(options.get("interact", True)),
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(proj)
