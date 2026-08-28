"""模拟导出器流程验证真实模板 templates/wallpaper_spine.html：
用 char003892（单页贴图）与 illust_dating14（11 页）的 base64 内联 + 相对贴图路径渲染，
覆盖模板本体的完整加载/取景/渲染路径（与 tools/spine41_test.html 互为镜像）。
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"D:\codex\browndust2-wallpaper\tools")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import verify_spine41 as V

REPO = V.REPO
TEMPLATE = REPO / "templates" / "wallpaper_spine.html"
EXTRACTED = V.EXTRACTED

ASSETS = {
    "char003892": (["char003892.skel", "char003892.atlas", "char003892.png"], r"(?:)/index.html"),
    "illust_dating14": (
        ["illust_dating14.skel", "illust_dating14.atlas"] + [f"illust_dating14_{i}.png" for i in range(2, 12)] + ["illust_dating14.png"],
        r"",  # 统一写到 index.html，asset 由查询参数区分：?asset=xxx
    ),
}


def make_index(asset: str) -> None:
    skel_name, atlas_name = f"{asset}.skel", f"{asset}.atlas"
    skel = (EXTRACTED / skel_name).read_bytes()
    atlas_text = (EXTRACTED / atlas_name).read_text(encoding="utf-8")
    pages = re.findall(r"^([^\r\n]+\.png)\s*$", atlas_text, re.M)
    textures = [{"page": p, "file": "assets/" + p} for p in pages]
    layers = [{  # 与 plugins/exporters/wallpaper_spine.py 的注入格式一致
        "name": asset,
        "skelData": base64.b64encode(skel).decode("ascii"),
        "atlasText": atlas_text,
        "textures": textures,
    }]
    html = TEMPLATE.read_text(encoding="utf-8")
    reps = {
        "LAYERS_JSON": json.dumps(layers, ensure_ascii=False),
        "BG_IMAGES_JSON": "[]",
        "BG_CSS": "background: #050510;",
        "VOICE_JSON": "null",
        "VOICE": "false",
        "INTRO": "false",
        "INTERACT": "true",
        "HIT_AREAS_JSON": "[]",
        "INTERACT_RULES_JSON": "[]",
        "SCALE": "100",
        "OFFSET_X": "0",
        "OFFSET_Y": "0",
        "ALIGNMENT": "center",
        "ANIMATION": json.dumps(""),
    }
    for k, v in reps.items():
        assert ("{{" + k + "}}") in html, f"占位符缺失: {k}"
        html = html.replace("{{" + k + "}}", v)
    assert "{{" not in html, "存在未替换占位符"
    (V.SERVE / f"export_{asset}.html").write_text(html, encoding="utf-8")


def main() -> None:
    V.build_serve_dir()
    # _serve 里放一份 3.8 名运行时，模拟旧导出器产物（模板 4.1 缺失时回退）
    shutil.copy2(V.RUNTIME_SRC, V.SERVE / "spine-webgl-3.8.js")
    for asset in ("char003892", "illust_dating14"):
        make_index(asset)
    httpd = V.start_server(V.PORT)
    try:
        for asset in ("char003892", "illust_dating14"):
            url = f"http://127.0.0.1:{V.PORT}/export_{asset}.html"
            # dump-dom 检查模板页就绪（模板没有 #out，靠 body 内 renderer 状态：title 用 canvas.ready 状态不设——
            # 改为检查截图像素 + 无 ERR title）
            shot = V.SHOTS / f"export_{asset}.png"
            V.run_edge([f"--screenshot={shot}", "--virtual-time-budget=20000"], url)
            if shot.exists():
                print(f"== 模板端到端 {asset} ==")
                V.analyze_png(shot, lambda line: print("  " + line))
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()