# -*- coding: utf-8 -*-
"""诊断下载失败：解析 char060301 的 bundle，检查大小并试下载。"""
import re
import sys

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

from pathlib import Path

from plugins.sources.cdn import CdnSource

cdn = CdnSource()
cdn.cache_dir = Path(r"D:\codex\browndust2-wallpaper\resources\metadata")
info = cdn.handshake(quality="HD")
print("version:", info.version)

for pid in ("char060301", "char062001", "char003892"):
    pats = [re.compile(rf"^UI/Prefabs/Spine/IllustSpine/illust_{pid}_", re.I)]
    targets = cdn.resolve_bundles(info, pats)
    print(f"\n{pid} 命中 {len(targets)} 个 bundle:")
    for k, s in list(targets.items())[:6]:
        print(f"  {s:,} B  {k}")

# 检查 group4 bundle 在 bundles TSV 里的登记大小
bt = cdn.bundles_tsv(info)
for line in bt.read_text(encoding="utf-8").splitlines():
    if "common-ui-prefabs-group4" in line:
        print("\ngroup4 登记:", line[:160])
        break
