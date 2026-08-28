# -*- coding: utf-8 -*-
"""验证 Alec char060301 下载链路（含 403 重试），后台快速验证。"""
import sys

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

import backend_server as bs  # noqa: E402

skin = bs.resolve_skin("Alec", "char060301")
print("skin:", skin)
result = bs.download_skin(skin)
print("ok:", result.get("ok"))
for d in result.get("downloaded", []):
    print("  ", d["path"][:70], "->", d["ok"])
print("error:", result.get("error"))
