"""落盘日志：打包版/开发版统一写到 %APPDATA%\\browndust2-wallpaper\\app.log。

frozen 的 windowed 模式（console=False）没有可用的 stdout/stderr，
"窗口自动退出 / 后端线程静默死亡"这类问题靠 print 完全看不到，
所以关键生命周期路径必须写文件。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "browndust2-wallpaper"
LOG_FILE = APP_DATA / "app.log"


def setup_logging() -> logging.Logger:
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(LOG_FILE),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            encoding="utf-8",
            force=True,
        )
    except Exception:  # noqa: BLE001
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("bd2")
