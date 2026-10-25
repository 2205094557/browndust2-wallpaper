# -*- coding: utf-8 -*-
"""背景图片 AI 超分模块（支持 Waifu2x / Real-CUGAN / Real-ESRGAN）。

针对官方场景图（resources/background）与扩图成品库（resources/input）生效：
- 通过 tools/<engine>-ncnn-vulkan/<version>/<engine>.exe 调用 GPU Vulkan 引擎
- Windows 下以 CREATE_NO_WINDOW 启动子进程（无黑弹窗）
- 放大产物统一存放在 resources/preview/ 临时预览目录中（母图持久保留，可随时重跑）
- 产物命名规范：原图名_引擎_倍率x[_n降噪][_tta][_downsample]_preview.png
- 退出软件后自动清理 resources/preview/ 目录
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from PIL import Image

from core.backgrounds import resolve_background_file

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BASE_DIR = Path(__file__).resolve().parent.parent

# 匹配由超分预览产生的文件名后缀：_算法_倍率x[_...]_preview 或历史 _2x/_4x 等
_UPSCALE_PREVIEW_RE = re.compile(r"(_[a-zA-Z0-9]+_\d+x.*_preview|_\d+x)+$", re.I)


def get_base_background_filename(filename: str) -> str:
    """从可能带有临时超分预览后缀的文件名中提取真实的原始母图文件名。

    例如：Scenery_waifu2x_4x_n0_preview.png -> Scenery.png
    """
    p = Path(filename)
    clean_stem = _UPSCALE_PREVIEW_RE.sub("", p.stem)
    return f"{clean_stem}{p.suffix}"


def clean_preview_dir() -> None:
    """清理 resources/preview 目录中的所有临时超分背景图片。"""
    preview_dir = BASE_DIR / "resources" / "preview"
    if not preview_dir.is_dir():
        return
    for item in preview_dir.iterdir():
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass


ALGORITHMS = {
    "waifu2x": "Waifu2x (推荐，极佳兼容，线条锐利)",
    "realcugan": "Real-CUGAN (二次元专属柔和)",
    "realesr": "Real-ESRGAN (通用精细渲染)",
}


def output_is_valid(path: Path) -> bool:
    """校验引擎产物是否可用：存在、非空、且能被 PIL 解码。

    不要用固定字节数阈值判断成功与否——小图正常输出也可能只有几十 KB。
    """
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def find_engine_exe(engine_name: str) -> str:
    """定位指定引擎的 exe 路径。"""
    base = BASE_DIR / "tools" / f"{engine_name}-ncnn-vulkan"
    if not base.is_dir():
        return ""
    for child in base.iterdir():
        if child.is_dir():
            exe = child / f"{engine_name}-ncnn-vulkan.exe"
            if exe.is_file():
                return str(exe)
    return ""


def _process_with_alpha_guard(
    src_png: str,
    out_png: str,
    engine_runner,
    scale: int,
) -> str:
    """若图片带 Alpha 通道，拆分 RGB 与 Alpha 分别处理（RGB 超分，Alpha 用 Lanczos 放大后合并）。"""
    with Image.open(src_png) as im:
        has_alpha = ("A" in im.getbands()) or (im.mode in ("RGBA", "LA", "PA"))
        if not has_alpha:
            return engine_runner(src_png, out_png)

        # 存在透明通道：拆分处理避免 ncnn 边缘黑边/杂色
        orig_rgba = im.convert("RGBA")
        r, g, b, a = orig_rgba.split()
        rgb_im = Image.merge("RGB", (r, g, b))

    out_p = Path(out_png)
    tmp_rgb = out_p.parent / f"_tmp_rgb_{out_p.name}"
    try:
        rgb_im.save(tmp_rgb, "PNG")
        upscaled_rgb_path = engine_runner(str(tmp_rgb), str(out_p))

        with Image.open(upscaled_rgb_path) as up_rgb:
            up_w, up_h = up_rgb.size
            a_resized = a.resize((up_w, up_h), Image.LANCZOS)
            up_rgb_conv = up_rgb.convert("RGBA")
            up_rgb_conv.putalpha(a_resized)
            up_rgb_conv.save(out_p, "PNG")

        return str(out_p)
    finally:
        if tmp_rgb.exists():
            tmp_rgb.unlink()


def upscale_waifu2x(png_path: str, out_path: str, scale: int = 2, denoise: int = 0, timeout: int = 600, tta: bool = False) -> str:
    exe = find_engine_exe("waifu2x")
    if not exe:
        raise FileNotFoundError("未找到 waifu2x-ncnn-vulkan 引擎，请检查 tools 目录")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    def _run(src: str, dst: str) -> str:
        d = max(0, min(3, int(denoise)))
        cmd = [exe, "-i", str(src), "-o", str(dst), "-s", str(scale), "-n", str(d), "-g", "0"]
        if tta:
            cmd.append("-x")

        result = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if result.returncode != 0 or not output_is_valid(Path(dst)):
            err = result.stderr.decode("utf-8", errors="replace")[-600:] if result.stderr else ""
            raise RuntimeError(f"waifu2x 放大失败 (exit={result.returncode}): {err}")
        return str(dst)

    return _process_with_alpha_guard(png_path, out_path, _run, scale)


def upscale_realcugan(png_path: str, out_path: str, scale: int = 2, noise: int = -1, timeout: int = 600, tta: bool = False) -> str:
    exe = find_engine_exe("realcugan")
    if not exe:
        raise FileNotFoundError("未找到 realcugan-ncnn-vulkan 引擎，请检查 tools 目录")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    def _run(src: str, dst: str) -> str:
        n = max(-1, min(3, int(noise)))
        cmd = [exe, "-i", str(src), "-o", str(dst), "-m", "models-se", "-n", str(n), "-s", str(scale), "-g", "0"]
        if tta:
            cmd.append("-x")
        res = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if res.returncode != 0 or not output_is_valid(Path(dst)):
            err = res.stderr.decode("utf-8", errors="replace")[-600:] if res.stderr else ""
            raise RuntimeError(f"realcugan 放大失败 (exit={res.returncode}): {err}")
        return str(dst)

    return _process_with_alpha_guard(png_path, out_path, _run, scale)


def upscale_realesr(png_path: str, out_path: str, scale: int = 2, timeout: int = 600, tta: bool = False) -> str:
    exe = find_engine_exe("realesrgan")
    if not exe:
        raise FileNotFoundError("未找到 realesrgan-ncnn-vulkan 引擎，请检查 tools 目录")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    def _run(src: str, dst: str) -> str:
        model_name = "realesrgan-x4plus-anime" if scale == 4 else "realesr-animevideov3-x2"
        cmd = [exe, "-i", str(src), "-o", str(dst), "-n", model_name, "-s", str(scale), "-g", "0", "-j", "1:1:1"]
        if tta:
            cmd.append("-x")

        result = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        has_vk_error = result.stderr and b"vkQueueSubmit failed" in result.stderr
        if result.returncode != 0 or not output_is_valid(Path(dst)) or has_vk_error:
            # 显卡兼容回退到 waifu2x
            if Path(dst).is_file():
                Path(dst).unlink()
            return upscale_waifu2x(src, dst, scale=scale, denoise=0, timeout=timeout, tta=tta)
        return str(dst)

    return _process_with_alpha_guard(png_path, out_path, _run, scale)


def upscale_background_image(
    filename: str,
    scale: int = 2,
    algorithm: str = "waifu2x",
    denoise: int = 0,
    tta: bool = False,
    downsample: bool = False,
) -> dict:
    """对原始场景图片执行超分，支持自定义降噪、TTA 采样与 4x->2x 超采样。"""
    preview_dir = BASE_DIR / "resources" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    # 1. 自动溯源母图：先剥掉超分预览后缀找官方/自定义原图，找不到再按字面文件名解析
    base_name = get_base_background_filename(filename)
    src_path = resolve_background_file(BASE_DIR, base_name) or resolve_background_file(BASE_DIR, filename)
    if src_path is None:
        raise FileNotFoundError(f"背景母图不存在: {base_name}")

    if scale not in (2, 4):
        scale = 2
    if algorithm not in ALGORITHMS:
        algorithm = "waifu2x"

    # 如果启用了 4x->2x 超采样方案
    run_scale = 4 if (scale == 2 and downsample) else scale

    # 2. 规范临时预览文件名（将核心参数编入文件名，形成独立精准缓存）
    clean_stem = _UPSCALE_PREVIEW_RE.sub("", src_path.stem)
    tag_parts = [clean_stem, algorithm, f"{scale}x"]
    if denoise != 0:
        tag_parts.append(f"n{denoise}")
    if tta:
        tag_parts.append("tta")
    if downsample and scale == 2:
        tag_parts.append("ds")
    tag_parts.append("preview")

    out_name = f"{'_'.join(tag_parts)}.png"
    out_file = preview_dir / out_name

    # 3. 检查 preview 缓存
    if output_is_valid(out_file):
        return {
            "ok": True,
            "filename": out_name,
            "cached": True,
            "message": f"已直接切换至现有的 {algorithm} {scale}x 高清背景",
        }

    # 4. 执行超分。引擎只吃 png：非 png 母图先在 preview 里转一份临时 png
    #    （成品库 input 不再为格式转换产生副本），跑完即删。
    src_for_engine = src_path
    tmp_src: Path | None = None
    if src_path.suffix.lower() != ".png":
        tmp_src = preview_dir / f"._src_{clean_stem}.png"
        with Image.open(src_path) as im:
            im.convert("RGBA" if "A" in im.getbands() else "RGB").save(tmp_src, "PNG")
        src_for_engine = tmp_src

    intermediate_file = str(out_file) if run_scale == scale else str(preview_dir / f"_tmp_{out_name}")
    try:
        if algorithm == "realcugan":
            cugan_noise = -1 if denoise <= 0 else (denoise - 1)
            out = upscale_realcugan(str(src_for_engine), intermediate_file, scale=run_scale, noise=cugan_noise, tta=tta)
        elif algorithm == "realesr":
            out = upscale_realesr(str(src_for_engine), intermediate_file, scale=run_scale, tta=tta)
        else:
            out = upscale_waifu2x(str(src_for_engine), intermediate_file, scale=run_scale, denoise=denoise, tta=tta)

        # 若是 4x->2x 超采样，进行高质量 Lanczos 缩放
        if run_scale == 4 and scale == 2 and downsample:
            with Image.open(out) as im:
                w2 = im.width // 2
                h2 = im.height // 2
                ds_im = im.resize((w2, h2), Image.LANCZOS)
                ds_im.save(out_file)
            if Path(out).exists():
                Path(out).unlink()
            out = str(out_file)

        final_p = Path(out)
        if not output_is_valid(final_p):
            if final_p.is_file():
                final_p.unlink()
            raise RuntimeError("超分输出图片异常（文件缺失或无法解码）")

        return {
            "ok": True,
            "filename": final_p.name,
            "cached": False,
            "message": f"超分放大完成 ({algorithm} {scale}x)",
        }
    finally:
        tmp_p = preview_dir / f"_tmp_{out_name}"
        if tmp_p.exists():
            tmp_p.unlink()
        if tmp_src is not None and tmp_src.exists():
            tmp_src.unlink()
