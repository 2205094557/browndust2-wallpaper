# -*- coding: utf-8 -*-
"""验证艾瑞克(char060301)主立绘下载（含 403 重试）。"""
import sys

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

import backend_server as bs  # noqa: E402

skin = bs.resolve_skin("艾瑞克", "char060301")
print("skin:", skin["name"] if skin else None)
result = bs.download_skin(skin)
print("ok:", result.get("ok"))
for d in result.get("downloaded", []):
    print("  ", d["path"][:80], "->", d["ok"])
print("error:", result.get("error"))
