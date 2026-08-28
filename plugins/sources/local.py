"""本地导入插件：扫描游戏 AssetBundles 目录（或已解包目录），复制/注册 bundle。"""

from __future__ import annotations

import shutil
from pathlib import Path

from core.registry import SourcePlugin


class LocalSource(SourcePlugin):
    id = "local"
    name = "本地游戏目录导入"

    def scan(self, assetbundles_dir: Path) -> list[Path]:
        """返回 AssetBundles 根目录下 spinepainting/dependencies 的文件列表。"""
        root = Path(assetbundles_dir)
        files = []
        for folder in ("spinepainting", "dependencies"):
            d = root / folder
            if d.is_dir():
                files.extend(p for p in d.iterdir() if p.is_file())
        return files

    def import_bundles(self, assetbundles_dir: Path, out_dir: Path, folders=("spinepainting", "dependencies")) -> dict:
        """把本地游戏目录里的相关 bundle 复制到资源目录（跳过已存在且大小一致的）。"""
        root = Path(assetbundles_dir)
        out_dir = Path(out_dir)
        copied = skipped = 0
        for folder in folders:
            d = root / folder
            if not d.is_dir():
                continue
            for src in d.iterdir():
                if not src.is_file():
                    continue
                dst = out_dir / folder / src.name
                if dst.exists() and dst.stat().st_size == src.stat().st_size:
                    skipped += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
        return {"copied": copied, "skipped": skipped}