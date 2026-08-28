"""官方 CDN 下载器。

M0：从参考实现中确认 CDN 地址与资源清单规则，实现单文件下载（断点续传）。
"""

from __future__ import annotations

from pathlib import Path


def download_bundle(bundle_name: str, out_dir: Path) -> Path:
    """按 bundle 名（如 spinepainting/xxx）从官方 CDN 下载并返回本地路径。"""
    raise NotImplementedError("M0")

