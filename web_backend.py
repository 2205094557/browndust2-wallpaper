"""pywebview 原生桥：桌面窗口里前端可不经 HTTP 直接调用的少量方法。

前端 bridge 只把 open_download_dir / open_extracted_dir 走 pywebview
原生路径（其余全部走 HTTP 后端 API），这里只保留该暴露面。
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class WebApi:
    """通过 window.pywebview.api 暴露给前端的方法。"""

    def ping(self) -> str:
        return "pong"

    def open_download_dir(self) -> dict:
        os.startfile(str(ROOT / "resources" / "bundles"))  # noqa: S606
        return {"ok": True}

    def open_extracted_dir(self) -> dict:
        os.startfile(str(ROOT / "resources" / "extracted"))  # noqa: S606
        return {"ok": True}
