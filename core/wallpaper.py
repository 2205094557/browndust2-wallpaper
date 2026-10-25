"""壁纸项目生成公共工具：模板渲染、project.json、背景样式。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from core.palette import extract_palette, find_palette_source, mode_css

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
WALLPAPER_LAYOUT = TEMPLATES / "wallpaper-layout.js"


def _vendor_file(name: str) -> Path:
    """运行时 JS 文件定位：开发版在 frontend/public/vendor，打包版在 frontend/dist/vendor（vite 把 public 复制到 dist）。"""
    for base in (ROOT / "frontend" / "public" / "vendor", ROOT / "frontend" / "dist" / "vendor"):
        p = base / name
        if p.exists():
            return p
    return ROOT / "frontend" / "public" / "vendor" / name


# BD2 的 skel 是 Spine 4.1 二进制（4.1.11 导出）：导出器把该 4.1 运行时复制进壁纸项目
SPINE_RUNTIME = _vendor_file("spine-webgl-4.1.js")
# BD2 互动引擎：预览(SpinePreview.vue)与壁纸同源加载，改一处两边同步
BD2_INTERACT = TEMPLATES / "shared" / "bd2-interact.js"

# 与 wallpaper-layout.js 的 ALIGN_ORDER / project.json combo 选项顺序一致
ALIGN_NAMES = ["center", "left-top", "right-top", "left-bottom", "right-bottom"]
ALIGN_LABELS = ["居中", "左上", "右上", "左下", "右下"]

BG_STYLES = {
    "solid": "background: linear-gradient(180deg, #182438, #0b0f17);",
    "gradient": "background: linear-gradient(135deg, #1d3f6e, #0e1b33 55%, #13294d);",
    "monet": (
        "background: radial-gradient(60% 70% at 20% 25%, rgba(122,92,255,.35), transparent 60%),"
        "radial-gradient(55% 65% at 80% 20%, rgba(58,167,255,.3), transparent 60%),"
        "radial-gradient(70% 80% at 50% 95%, rgba(255,122,92,.22), transparent 60%),"
        "linear-gradient(160deg, #141b2e, #0b0f17);"
    ),
    "frost": (
        "background: radial-gradient(45% 55% at 30% 30%, rgba(58,167,255,.25), transparent 60%),"
        "radial-gradient(45% 55% at 75% 70%, rgba(122,92,255,.22), transparent 60%),"
        "linear-gradient(180deg, #101826, #0b0f17);"
    ),
    "star": (
        "background: radial-gradient(1.5px 1.5px at 20% 30%, rgba(255,255,255,.7), transparent 60%),"
        "radial-gradient(1.5px 1.5px at 60% 15%, rgba(255,255,255,.6), transparent 60%),"
        "radial-gradient(1.5px 1.5px at 80% 45%, rgba(255,255,255,.5), transparent 60%),"
        "radial-gradient(1.5px 1.5px at 40% 70%, rgba(255,255,255,.55), transparent 60%),"
        "radial-gradient(1.5px 1.5px at 90% 80%, rgba(255,255,255,.45), transparent 60%),"
        "linear-gradient(180deg, #101a2e, #080c14);"
    ),
}


def bg_css(bg: str) -> str:
    return BG_STYLES.get(bg, BG_STYLES["monet"])


def bg_css_for_skin(
    skin: dict,
    root,
    bg: str,
    bg_color: str | None = None,
    bg_image: str | None = None,
    bg_scale: int = 100,
    bg_offset_x: int = 0,
    bg_offset_y: int = 0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> str:
    """预览与导出共用的背景 CSS：所有模式都优先按皮肤素材取色生成，取色失败才用固定样式。"""
    if bg == "image" and bg_image:
        scale_pct = bg_scale or 100
        # 锚点 = 画面中心 + (整体偏移 + 背景独立偏移)：与预览 autoBgStyle /
        # WebGL drawBg 同语义——整体平移时人物与背景一起动，缩放绕同一锚点。
        # 整体 offsetY 向下为正（画面跟随鼠标），bgOffsetY 世界坐标向上为正。
        pos_x = f"calc(50% + {(bg_offset_x or 0) + (offset_x or 0)}vw)"
        pos_y = f"calc(50% + {(offset_y or 0) - (bg_offset_y or 0)}vh)"
        return (
            f"background-image: url('{bg_image}'); "
            f"background-size: {scale_pct}% auto; background-position: {pos_x} {pos_y}; background-repeat: no-repeat;"
        )
    src = find_palette_source(skin, root)
    palette = extract_palette(src) if src else None
    if palette:
        return mode_css(bg, palette, solid_color=bg_color)
    if bg == "solid" and bg_color:
        return f"background: {bg_color};"
    return bg_css(bg)


def project_dir_name(ship: str, name: str) -> str:
    """生成安全的壁纸项目目录名。

    每次导出追加 8 位随机后缀：Wallpaper Engine 按“目录路径”记忆滑块覆盖值，
    同一目录重复导出会沿用旧覆盖值导致导出的偏移“不生效”。新目录 = 全新壁纸，
    首次推送即导出值，所见即所得。Windows 不允许目录名以空格/点结尾，也禁止
    <>:"/\\|?* 等字符。
    """
    raw = f"{ship}_{name}"
    cleaned = "".join(ch for ch in raw if ch not in '<>:"/\\|?*').rstrip(" .")
    return f"{cleaned or 'wallpaper'}_{uuid.uuid4().hex[:8]}"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# 内置兜底预览图（16x9 纯色 JPEG，631B）。PIL 缺失/图片损坏时用它落盘，
# 保证 project.json 引用的 preview 文件真实存在——WE 对不存在的 preview 会
# 每秒抛 icon create err (-2147467259)，托盘图标失效并留在「无渲染进程」的坏状态
# （实测 WE log.txt 435 行全是该错误，且 webwallpaper64 消失）。
_FALLBACK_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000d090a0b0a080d0b0a0b0e0e0d0f13201513"
    "121213271c1e17202e2931302e292d2c333a4a3e333646372c2d405741464c4e525352323e5a615a5060"
    "4a51524fffdb0043010e0e0e131113261515264f352d354f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f"
    "4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4fffc0001108000900"
    "1003012200021101031101ffc4001f000001050101010101010000000000000000010203040506070809"
    "0a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114"
    "328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a43444546"
    "4748494a535455565758595a636465666768696a737475767778797a838485868788898a929394959697"
    "98999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2"
    "e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102"
    "030405060708090a0bffc400b51100020102040403040705040400010277000102031104052131061241"
    "510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a3536"
    "3738393a434445464748494a535455565758595a636465666768696a737475767778797a828384858687"
    "88898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3"
    "d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00e068a28a"
    "d883ffd9"
)


def write_preview_from_data_url(proj: Path, data_url: str) -> Path | None:
    """把前端截取的预览帧（PNG dataURL）写成壁纸项目的 preview.jpg 封面。

    WE 的封面必须是「预览里看到的那个构图」：直接把预览画布截图作为封面，
    与导出结果天然一致。旧实现是「挑 assets 里最大的 PNG」，但 BD2 的骨架贴图
    是整张 2048×2048 图集（部件平铺），挑中它就是一堆碎片；挑中扩图背景则只有
    背景没有角色——两种都不是封面。
    """
    import base64

    if not data_url or "," not in data_url:
        return None
    try:
        png = base64.b64decode(data_url.split(",", 1)[1])
    except Exception:  # noqa: BLE001
        return None
    if not png.startswith(b"\x89PNG"):
        return None
    preview_file = proj / "preview.jpg"
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(png)) as im:
            im = im.convert("RGB")
            # 封面统一裁成 16:9（与预览 stage / WE 取景一致），最长边 640
            w, h = im.size
            if h and abs(w / h - 16 / 9) > 1e-3:
                target_h = int(round(w * 9 / 16))
                if target_h <= h:  # 裁上下
                    top = (h - target_h) // 2
                    im = im.crop((0, top, w, top + target_h))
                else:  # 裁左右
                    target_w = int(round(h * 16 / 9))
                    left = max(0, (w - target_w) // 2)
                    im = im.crop((left, 0, left + target_w, h))
            im.thumbnail((640, 360), Image.Resampling.LANCZOS)
            im.save(preview_file, "JPEG", quality=85)
            return preview_file
    except Exception as ex:  # noqa: BLE001
        print(f"[preview] 写入预览封面失败: {ex}", flush=True)
        return None


def generate_preview_image(proj: Path, bg_img_file: Path | str | None = None) -> Path:
    """为壁纸项目生成 preview.jpg 缩略图（若不存在）。

    Wallpaper Engine 读取 project.json 的 preview 字段展示缩略图与托盘图标。
    若引用的文件不存在，WE 托盘与浏览器会每秒抛出 icon create err: -2147467259。
    因此本函数【返回时保证 preview.jpg 已落盘】：PIL 缺失或图片损坏时写内置兜底图，
    绝不把「指向不存在文件的 preview 引用」留给 WE。

    优先级：
      1. 已有 preview.jpg（例如前端截图写入的封面）——直接复用；
      2. 指定背景图（静态壁纸的整图 / 用户选取的扩图背景）；
      3. assets 里最大的 PNG（**注意**：BD2 骨架贴图是平铺图集，仅在无更好来源时用）；
      4. 纯色兜底。
    """
    preview_file = proj / "preview.jpg"
    if preview_file.exists():
        return preview_file
    try:
        from PIL import Image

        # 1. 优先使用背景图
        if bg_img_file:
            bg_path = Path(bg_img_file)
            if bg_path.exists():
                with Image.open(bg_path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((640, 360), Image.Resampling.LANCZOS)
                    im.save(preview_file, "JPEG", quality=85)
                    return preview_file

        # 2. 从 assets 寻找最大的立绘/背景贴图
        assets_dir = proj / "assets"
        if assets_dir.is_dir():
            pngs = list(assets_dir.glob("*.png"))
            if pngs:
                largest_png = max(pngs, key=lambda p: p.stat().st_size)
                with Image.open(largest_png) as im:
                    if im.mode == "RGBA":
                        bg = Image.new("RGB", im.size, (24, 36, 56))
                        bg.paste(im, mask=im.split()[3])
                        im = bg
                    else:
                        im = im.convert("RGB")
                    im.thumbnail((640, 360), Image.Resampling.LANCZOS)
                    im.save(preview_file, "JPEG", quality=85)
                    return preview_file

        # 3. 兜底纯色背景
        im = Image.new("RGB", (640, 360), (20, 27, 46))
        im.save(preview_file, "JPEG", quality=85)
    except Exception as ex:  # noqa: BLE001
        print(f"[preview] 生成 preview.jpg 失败，改用内置兜底图: {ex}", flush=True)
    if not preview_file.exists():
        # 兜底：PIL 缺失/图片损坏也必须留下真实文件——project.json 已写死引用
        # preview.jpg，留一个空引用会让 WE 每秒报 icon create err
        preview_file.write_bytes(_FALLBACK_JPEG)
    return preview_file


def project_json(
    title: str,
    preview: str = "preview.jpg",
    scale: int = 100,
    offset_x: int = 0,
    offset_y: int = 0,
    char_offset_x: int | None = None,
    char_offset_y: int | None = None,
    alignment: int = 0,
    animations: list[str] | None = None,
    animation: str = "",
    voice: bool = True,
    intro: bool = True,
    interact: bool = True,
    hitareas: bool | None = None,
    presets: list[str] | None = None,
) -> dict:
    # 语义与预览一致：scale 为百分比（100 = 自适应），偏移为画布宽/高百分比
    scale_ctl = int(_clamp(scale, 20, 300))
    ox = int(_clamp(offset_x, -100, 100))
    oy = int(_clamp(offset_y, -100, 100))

    # 采用 Wallpaper Engine 编辑器自己保存的字段格式（editable/fraction/index/order），
    # 避免 WE 导入时对滑块 value 做二次换算/误写覆盖值。
    def slider(text: str, value: int, lo: int, hi: int, order: int, index: int) -> dict:
        return {
            "text": text,
            "type": "slider",
            "value": value,
            "min": lo,
            "max": hi,
            "editable": True,
            "fraction": False,
            "index": index,
            "order": order,
        }

    def bool_ctl(text: str, value: bool, order: int, index: int) -> dict:
        return {
            "text": text,
            "type": "bool",
            "value": bool(value),
            "editable": True,
            "index": index,
            "order": order,
        }

    properties = {
        "scalectrl": slider("缩放", scale_ctl, 20, 300, 103, 3),
        "offsetx": slider("水平偏移", ox, -100, 100, 101, 1),
        "offsety": slider("垂直偏移", oy, -100, 100, 102, 2),
        "alignment": {
            "text": "对齐方式", "type": "combo",
            # WE combo 标准格式：value 是选中项的字符串值，options 是 {label,value} 对象数组。
            # 旧格式（整数索引 + 字符串数组）会导致该属性在 WE 侧边栏不显示。
            "value": (
                ALIGN_NAMES[alignment]
                if isinstance(alignment, int) and 0 <= alignment < len(ALIGN_NAMES)
                else str(alignment or "center")
            ),
            "options": [
                {"label": label, "value": name}
                for name, label in zip(ALIGN_NAMES, ALIGN_LABELS)
            ],
            # editable 必须为 true：WE 属性面板只显示 editable 的属性，
            # 漏掉该字段会导致「对齐方式」在 WE 控件里不显示
            "editable": True,
            "index": 0,
            "order": 100,
        },
    }

    # 多预设（动画 + 背景 + 构图一键切换）：有预设时生成下拉控件，
    # 初始值 = 首个预设（与模板烘入的初始状态一致）
    preset_names = [str(n) for n in (presets or []) if str(n).strip()]
    if preset_names:
        properties["preset"] = {
            "text": "预设",
            "type": "combo",
            "value": preset_names[0],
            "options": [{"label": n, "value": n} for n in preset_names],
            "editable": True,
            "index": 0,
            "order": 99,
        }

    # 角色独立偏移（只移骨架，背景不动）：仅 Spine 壁纸提供该控件
    #（静态壁纸是整张图，无“角色/背景”分层，不生成无意义滑块）。
    if char_offset_x is not None:
        properties["charoffsetx"] = slider("角色水平偏移", int(_clamp(char_offset_x, -100, 100)), -100, 100, 104, 4)
    if char_offset_y is not None:
        properties["charoffsety"] = slider("角色垂直偏移", int(_clamp(char_offset_y, -100, 100)), -100, 100, 111, 11)

    # Spine 互动皮肤专属开关：互动语音/互动。
    # 开场动画（playintro）仅皮肤有 login 动画时生成（导出器自动检测 has_login）。
    # 导出时关闭的功能不生成对应属性（WE 面板不出现、壁纸不带该功能）。
    if voice:
        properties["voice"] = bool_ctl("语音", voice, 105, 5)
    if intro:
        properties["playintro"] = bool_ctl("开场动画", intro, 106, 6)
    if interact:
        properties["interact"] = bool_ctl("互动", interact, 107, 7)
    # BD2 拟官方互动的区域调试层开关（hitareas=None 表示宿主不生成该控件）
    if hitareas is not None:
        properties["showhitareas"] = bool_ctl("显示互动区域", hitareas, 109, 9)

    return {
        "file": "index.html",
        "general": {"properties": properties},
        "title": title,
        "type": "web",
        "preview": preview,
    }


def export_defaults(options: dict) -> dict:
    """把预览的缩放/偏移/对齐换算成壁纸 HTML 初始值（与预览语义一致）。"""
    scale = int(_clamp(int(options.get("scale", 100) or 100), 20, 300))
    ox = int(_clamp(int(options.get("offsetX", 0) or 0), -100, 100))
    oy = int(_clamp(int(options.get("offsetY", 0) or 0), -100, 100))
    cox = int(_clamp(int(options.get("charOffsetX", 0) or 0), -100, 100))
    coy = int(_clamp(int(options.get("charOffsetY", 0) or 0), -100, 100))
    # 人物旋转（度，正=顺时针）：预览"人物旋转"调节项同值烘进模板，只转人物层；
    # 与 CHAR_OFFSET 一样不生成 WE 控件（导出即所见）
    rot = int(_clamp(int(options.get("rotation", 0) or 0), -180, 180))
    # 背景图独立位移（%）：只移动背景图（预览 drawBg 同语义）；其他项目模板无
    # {{BG_OFFSET_*}} 占位时替换为 no-op，无副作用
    box = int(_clamp(int(options.get("bgOffsetX", 0) or 0), -100, 100))
    boy = int(_clamp(int(options.get("bgOffsetY", 0) or 0), -100, 100))
    align = options.get("alignment", 0)
    align_name = ALIGN_NAMES[align] if isinstance(align, int) and 0 <= align < len(ALIGN_NAMES) else str(align or "center")
    anim = options.get("animation") or ""
    return {
        "SCALE": str(scale),
        "OFFSET_X": str(ox),
        "OFFSET_Y": str(oy),
        "CHAR_OFFSET_X": str(cox),
        "CHAR_OFFSET_Y": str(coy),
        "CHAR_ROTATION": str(rot),
        "BG_OFFSET_X": str(box),
        "BG_OFFSET_Y": str(boy),
        "ALIGNMENT": align_name,
        "ANIMATION": json.dumps(str(anim), ensure_ascii=False),
    }


def render_template(name: str, **replacements) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    # 防呆护栏：占位符未全部替换（如运行中的旧后端进程缺新导出键，而模板文件
    # 已更新）会把字面 {{XXX}} 烘进 JS——整段脚本语法死亡，壁纸人物背景全灭
    #（2026-10 CHAR_ROTATION 实测）。宁可导出时报错，不产出坏壁纸。
    import re as _re
    leftover = sorted(set(_re.findall(r"\{\{[A-Z][A-Z0-9_]*\}\}", text)))
    if leftover:
        raise ValueError(f"模板 {name} 存在未替换的占位符: {', '.join(leftover)}（后端进程可能需要重启以加载新导出键）")
    return text
