# -*- coding: utf-8 -*-
"""端到端验证：导出黎维塔-享乐主义者为 Wallpaper Engine 壁纸项目。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

import backend_server as bs  # noqa: E402

result = bs.export_skin("Liberta", "char003892", "Hedonist", {
    "root": str(bs.ROOT),
    "bg": "auto",
    "voice": True,
    "intro": True,
    "interact": True,
})
print("export ok:", result.get("ok"))
proj = result.get("project") or ""
print("project:", proj)
if result.get("error"):
    print("error:", result["error"])
p = Path(proj) if proj else None
if p and p.is_dir():
    for f in sorted(p.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(p)}  {f.stat().st_size:,}")
    pj = json.loads((p / "project.json").read_text(encoding="utf-8"))
    print("project.json title:", pj.get("title"))
