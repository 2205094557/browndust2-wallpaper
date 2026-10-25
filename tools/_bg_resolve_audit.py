# -*- coding: utf-8 -*-
"""一次性审计：模拟前端导出背景的文件名 → 后端 resolve_background_file，
检查解析结果是否落在当前皮肤自己的提取目录（找“导出了别的皮肤背景”的错位）。"""
import sys
import json
import re

sys.path.insert(0, ".")
from pathlib import Path
from core.backgrounds import resolve_background_file

d = json.load(open("resources/metadata/local_skins.json", encoding="utf-8"))


def bgset_for_anim(anim, maxset):
    m = re.search(r"(\d+)\s*$", anim or "")
    n = int(m.group(1)) if m else 1
    return max(1, min(n or 1, maxset))


bad = []
for s in d:
    a = s.get("asset", {})
    sets = a.get("bg_sets") or {}
    refs = {}
    if sets:
        mx = max(int(k) for k in sets)
        for st in ("1", str(bgset_for_anim("loop", mx))):
            if sets.get(st):
                refs[sets[st]] = "set" + st
    for l in a.get("layers", []):
        if l.get("bg"):
            refs[l["bg"]] = "layer"
    for name in refs:
        p = resolve_background_file(Path("."), name)
        loc = str(p).replace("\\", "/") if p else "(未找到)"
        if not p or s["bundle"] not in loc:
            bad.append((s["ship"], s["name"], s["bundle"], name, refs[name], loc))

print("解析错位的皮肤数:", len(bad))
for b in bad:
    print(" ", b[0], "|", b[1], "|", b[2], "| 请求:", b[3], "|", b[4], "| 实际解析 →", b[5])
