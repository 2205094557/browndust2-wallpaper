"""静态立绘壁纸导出插件：把静态立绘 PNG 生成为 WE web 壁纸项目。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.registry import ExporterPlugin
from core.wallpaper import (
    bg_css_for_skin,
    export_defaults,
    project_dir_name,
    project_json,
    render_template,
)


class WallpaperStaticExporter(ExporterPlugin):
    id = "wallpaper_static"
    name = "静态立绘壁纸导出"

    def export(self, skin: dict, options: dict, out_dir: str) -> str:
        out = Path(out_dir)
        proj = out / project_dir_name(skin["ship"], skin["name"])
        assets = proj / "assets"
        assets.mkdir(parents=True, exist_ok=True)

        src_dir = Path(options["root"]) / "resources" / skin["asset"]["dir"]
        image = skin["asset"].get("image", "painting.png")
        shutil.copy2(src_dir / image, assets / image)

        html = render_template(
            "wallpaper_static.html",
            IMAGE="assets/" + image,
            BG_CSS=bg_css_for_skin(
                skin, options.get("root"), options.get("bg", "monet"), options.get("bgColor")
            ),
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
                    alignment=options.get("alignment", 0),
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(proj)
