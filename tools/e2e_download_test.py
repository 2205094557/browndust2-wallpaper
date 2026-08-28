# -*- coding: utf-8 -*-
"""端到端验证：通过 backend_server.download_skin 下载并提取黎维塔-享乐主义者主立绘。"""
import sys

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

import backend_server as bs  # noqa: E402

skin = bs.resolve_skin("Liberta", "char003892")
print("downloading:", skin)
result = bs.download_skin(skin)
print("ok:", result.get("ok"))
print("downloaded:", result.get("downloaded"))
print("error:", result.get("error"))
