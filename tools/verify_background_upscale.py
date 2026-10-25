# -*- coding: utf-8 -*-
"""棕色尘埃2 背景超分与扩图工作流端到端测试脚本。

测试内容：
1. 引擎存在性与调用校验
2. 导出扩图到 output 目录
3. 外部扩图成品模拟（jpg 放入 input 目录）
4. 刷新成品库 input（扫描 + 缩略图；不复制不转换，未扩图原样丢回只提示）
5. AI 背景超分（调用 waifu2x 2x 超分放大）
6. Spine 壁纸导出（背景图进包 assets/ + BG_CSS 注入）
7. 删除成品库背景（删的就是 input 里的文件）与缩略图清理
8. 结束后清理测试产生的临时文件
"""

from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.backgrounds import (
    background_dirs,
    custom_thumb_name,
    delete_custom_background,
    export_background_for_outpaint,
    get_available_backgrounds,
    import_outpaint_results,
    migrate_legacy_custom,
    resolve_background_file,
)
from core.upscaler import (
    clean_preview_dir,
    find_engine_exe,
    output_is_valid,
    upscale_background_image,
)
from plugins.exporters.wallpaper_spine import WallpaperSpineExporter


def log_step(name: str, passed: bool, detail: str = ""):
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name} {detail}")
    if not passed:
        raise AssertionError(f"Step failed: {name} - {detail}")


def run_tests():
    print("=== 开始背景超分与扩图工作流端到端验证 ===")
    dirs = background_dirs(ROOT)
    dirs.official.mkdir(parents=True, exist_ok=True)
    dirs.legacy_custom.mkdir(parents=True, exist_ok=True)
    dirs.output.mkdir(parents=True, exist_ok=True)
    dirs.input.mkdir(parents=True, exist_ok=True)
    dirs.preview.mkdir(parents=True, exist_ok=True)

    tag = f"test_bg_{uuid.uuid4().hex[:6]}"
    test_official_name = f"{tag}_base.png"
    test_official_file = dirs.official / test_official_name

    cleanup_files: list[Path] = [test_official_file]

    try:
        # 0. 检查超分引擎
        exe_w2x = find_engine_exe("waifu2x")
        log_step("定位 waifu2x 引擎", bool(exe_w2x and Path(exe_w2x).is_file()), exe_w2x)

        # 创建一个官方测试底图 (160x90)
        base_img = Image.new("RGBA", (160, 90), (45, 65, 105, 255))
        for x in range(20, 140, 10):
            for y in range(20, 70, 10):
                base_img.putpixel((x, y), (200, 180, 120, 255))
        base_img.save(test_official_file, "PNG")

        # 1. 测试 resolve_background_file
        resolved = resolve_background_file(ROOT, test_official_name)
        log_step("背景原图解析", bool(resolved and resolved.resolve() == test_official_file.resolve()))

        # 2. 测试导出扩图 export_background_for_outpaint
        exp_res = export_background_for_outpaint(ROOT, test_official_name)
        exported_file = dirs.output / test_official_name
        cleanup_files.append(exported_file)
        readme_file = dirs.output / "扩图说明.txt"
        log_step("导出扩图到 output", exp_res.get("ok") and exported_file.is_file())
        log_step("扩图说明文件生成", readme_file.is_file())

        # 3. 模拟外部扩图：生成一个 jpg 文件到 input 目录，同时放一份同名未修改的官方图到 input
        expanded_tag = f"{tag}_expanded"
        input_jpg = dirs.input / f"{expanded_tag}.jpg"
        expanded_img = Image.new("RGB", (240, 90), (30, 40, 70))
        expanded_img.paste(base_img.convert("RGB"), (40, 0))
        expanded_img.save(input_jpg, "JPEG")
        cleanup_files.append(input_jpg)

        # 放入未修改的原始导出，测试防误操作跳过逻辑
        unmodified_in_input = dirs.input / test_official_name
        shutil.copy2(exported_file, unmodified_in_input)
        cleanup_files.append(unmodified_in_input)

        # 4. 测试导入扩图成果 import_outpaint_results
        imp_res = import_outpaint_results(ROOT)
        log_step("刷新成品库返回 ok", bool(imp_res.get("ok")))
        library_name = f"{expanded_tag}.jpg"
        thumb_file = ROOT / "resources" / "thumbnails" / "background" / custom_thumb_name(library_name)
        cleanup_files.append(thumb_file)

        log_step("成品库文件原地可用（不复制不转换）",
                 library_name in (imp_res.get("imported") or []) and input_jpg.is_file()
                 and not (dirs.input / f"{expanded_tag}.png").exists())
        log_step("未扩图原样丢回只提示不隐藏",
                 test_official_name in (imp_res.get("unchanged") or [])
                 and test_official_name in (imp_res.get("imported") or []))
        log_step("成品库缩略图生成", thumb_file.is_file())

        # 幂等刷新：文件没变，列表内容也不变（不再有“导入过就消失”的语义）
        imp_res2 = import_outpaint_results(ROOT)
        log_step("重复刷新结果一致", (imp_res2.get("imported") or []) == (imp_res.get("imported") or []))

        # 5. 测试获取背景列表 get_available_backgrounds（成品库 = input）
        bgs = get_available_backgrounds(dirs.official, dirs.input)
        custom_item = next((b for b in bgs if b["filename"] == library_name), None)
        log_step("背景列表可见成品库条目", bool(custom_item and custom_item["source"] == "custom"))

        # 5b. 旧版 custom 持久库迁移并入 input
        legacy_file = dirs.legacy_custom / f"{tag}_legacy.png"
        base_img.save(legacy_file, "PNG")
        migrated = migrate_legacy_custom(ROOT)
        moved_file = dirs.input / legacy_file.name
        cleanup_files.append(moved_file)
        log_step("旧 custom 成品并入 input",
                 migrated >= 1 and moved_file.is_file() and not legacy_file.exists())

        # 6. 测试 AI 背景超分
        print("  正在执行 waifu2x 2x 超分测试...")
        up_res = upscale_background_image(library_name, scale=2, algorithm="waifu2x", denoise=0)
        log_step("超分返回 ok", bool(up_res.get("ok")))
        up_filename = up_res.get("filename") or ""
        up_file = dirs.preview / up_filename
        cleanup_files.append(up_file)
        log_step("超分产物文件生成", up_file.is_file())

        with Image.open(up_file) as up_im:
            w_exp, h_exp = expanded_img.width * 2, expanded_img.height * 2
            log_step("超分产物尺寸翻倍 (2x)", up_im.size == (w_exp, h_exp), f"got {up_im.size} vs expected {(w_exp, h_exp)}")

        # 缓存命中测试
        up_res_cached = upscale_background_image(library_name, scale=2, algorithm="waifu2x", denoise=0)
        log_step("超分缓存命中", bool(up_res_cached.get("cached")))

        # 7. 测试 Spine 壁纸导出整合（带超分背景）
        # 构造 mock skin
        mock_skin = {
            "ship": "测试角色",
            "name": "测试皮肤",
            "painting": "char003892",
            "asset": {
                "dir": "extracted/spine/char003892",
                "layers": [],
            },
        }
        test_out_dir = ROOT / "resources" / "wallpapers" / f"test_export_{tag}"
        cleanup_files.append(test_out_dir)

        exporter = WallpaperSpineExporter()
        proj_dir = exporter.export(
            mock_skin,
            {
                "root": str(ROOT),
                "bg": "image",
                "bgImage": up_filename,
                "bgScale": 140,
                "bgOffsetX": 5,
                "bgOffsetY": -3,
            },
            str(test_out_dir.parent),
        )
        proj_path = Path(proj_dir)
        cleanup_files.append(proj_path)

        log_step("壁纸项目导出成功", proj_path.is_dir())
        asset_bg = proj_path / "assets" / up_filename
        log_step("超分背景进包 assets/", asset_bg.is_file())
        html_content = (proj_path / "index.html").read_text(encoding="utf-8")
        log_step("index.html 包含背景图 url 引用", f"url('assets/{up_filename}')" in html_content)
        log_step("index.html 包含背景缩放比例 140%", "background-size: 140% auto" in html_content)

        # 8. 测试删除自定义背景 delete_custom_background
        del_res = delete_custom_background(ROOT, library_name)
        log_step("从成品库删除背景", bool(del_res.get("ok")))
        log_step("input 里的文件已被删除", not input_jpg.exists())
        log_step("成品库缩略图已被清理", not thumb_file.exists())

        print("=== 全链路背景超分与扩图工作流验证全部通过！ ===")

    finally:
        # 清理测试产生的临时文件与目录
        for p in cleanup_files:
            try:
                if p.is_file():
                    p.unlink()
                elif p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    run_tests()
