# -*- coding: utf-8 -*-
"""characters.json → skins.json：把每个服装的四类能力展开为可下载条目。

BD2 数据模型：一个服装(charXXXXXX)最多有四种可下载内容，全部映射到
spine/static 两种渲染器：
- 主立绘  → spine, painting=charXXXXXX
- 约会    → spine, painting=illust_datingN（Fated Guest 互动立绘）
- Ultimate→ spine, painting=cutscene_charXXXXXX（技能演出）
- 静态    → static, painting=illust_charXXXXXX_NNN（图鉴大图）

前端图鉴按 ship(人物) 分组展示这些条目，与碧蓝的交互完全一致。
"""
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"


def main():
    chars = json.loads((MD / "characters.json").read_text(encoding="utf-8"))
    skins = []
    for c in chars:
        cid = c.get("id", "")
        if not re.fullmatch(r"\d{6}", cid):
            continue
        costume_id = f"char{cid}"
        ship = c.get("char") or "Unknown"
        costume = c.get("costume") or cid
        sort = c.get("sort", 9999)
        # 主立绘（所有可玩服装都有）
        skins.append({
            "ship": ship, "name": costume, "painting": costume_id,
            "bundle": costume_id, "type": "spine", "sort": sort,
        })
        # 约会立绘
        dating = (c.get("dating") or "").lower()
        if dating.startswith("illust_dating"):
            skins.append({
                "ship": ship, "name": f"{costume} · 约会", "painting": dating,
                "bundle": dating, "type": "spine", "sort": sort,
            })
        # Ultimate 演出
        cutscene = (c.get("cutscene") or "").lower()
        if cutscene.startswith("cutscene_"):
            skins.append({
                "ship": ship, "name": f"{costume} · Ultimate", "painting": cutscene,
                "bundle": cutscene, "type": "spine", "sort": sort,
            })
        # 静态立绘
        static_key = c.get("static") or ""
        m = re.search(r"(illust_char\d{6}_\d+)\.png$", static_key, re.I)
        if m:
            painting = m.group(1).lower()
            skins.append({
                "ship": ship, "name": f"{costume} · 立绘", "painting": painting,
                "bundle": painting, "type": "static", "sort": sort,
            })
    (MD / "skins.json").write_text(json.dumps(skins, ensure_ascii=False, indent=1), encoding="utf-8")
    print("skins:", len(skins))


if __name__ == "__main__":
    main()
