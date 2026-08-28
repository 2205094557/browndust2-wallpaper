"""本地资源库：SQLite 记录舰船/皮肤/资源状态。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ships(
  id TEXT PRIMARY KEY,
  name TEXT, faction TEXT, rarity TEXT, hull TEXT, no TEXT, en TEXT
);
CREATE TABLE IF NOT EXISTS skins(
  id TEXT PRIMARY KEY,
  ship TEXT, name TEXT, bundle TEXT, type TEXT, status TEXT,
  asset_dir TEXT, asset_model TEXT, asset_layers TEXT
);
"""


class Library:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.executescript(SCHEMA)

    def import_metadata(self, ships: list[dict], skins: list[dict], local_skins: list[dict]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM ships")
            self.conn.execute("DELETE FROM skins")
            for s in ships:
                self.conn.execute(
                    "INSERT OR REPLACE INTO ships(id,name,faction,rarity,hull,no,en) VALUES(?,?,?,?,?,?,?)",
                    (
                        s.get("name"), s.get("name"), s.get("faction", ""),
                        s.get("rarity", ""), s.get("hull", ""), s.get("no", ""), s.get("en", ""),
                    ),
                )
            for sk in skins:
                # 优先按 painting 精确匹配本地资源；同一 ship+bundle 可能对应多个皮肤
                # （DOA 联动基础皮与动态皮肤 bundle 均为空），此时不能按 ship+bundle
                # 回退，否则会把基础皮肤的静态资源误挂到动态皮肤上。仅当该键唯一时才回退。
                painting = sk.get("painting") or ""
                loc = next(
                    (l for l in local_skins if (l.get("painting") or "") == painting),
                    None,
                )
                if loc is None:
                    same_key = [
                        s
                        for s in skins
                        if s.get("ship") == sk.get("ship") and s.get("bundle") == sk.get("bundle")
                    ]
                    if len(same_key) == 1:
                        loc = next(
                            (
                                l
                                for l in local_skins
                                if l.get("ship") == sk.get("ship") and l.get("bundle") == sk.get("bundle")
                            ),
                            None,
                        )
                asset = (loc or {}).get("asset") or {}
                # 主键加入 painting，避免同 ship+bundle 的多个皮肤相互覆盖
                skin_id = f"{sk.get('ship')}|{sk.get('bundle')}|{painting}"
                self.conn.execute(
                    "INSERT OR REPLACE INTO skins(id,ship,name,bundle,type,status,asset_dir,asset_model,asset_layers) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        skin_id, sk.get("ship"), sk.get("name"), sk.get("bundle", ""),
                        (loc or {}).get("type", "unknown"),
                        "downloaded" if loc else "remote",
                        asset.get("dir", ""),
                        asset.get("model", ""),
                        json.dumps(asset.get("layers", []), ensure_ascii=False),
                    ),
                )

    def list_ships(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name,faction,rarity,hull,no,en FROM ships ORDER BY name"
        ).fetchall()
        return [
            {"name": r[0], "faction": r[1], "rarity": r[2], "hull": r[3], "no": r[4], "en": r[5]}
            for r in rows
        ]

    def list_skins(self, ship: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name,bundle,type,status,asset_dir,asset_model,asset_layers FROM skins WHERE ship=? ORDER BY bundle",
            (ship,),
        ).fetchall()
        out = []
        for r in rows:
            entry = {"name": r[0], "bundle": r[1], "type": r[2], "status": r[3]}
            if r[4]:
                entry["asset"] = {"dir": r[4], "model": r[5], "layers": json.loads(r[6] or "[]")}
            else:
                entry["asset"] = None
            out.append(entry)
        return out

    def downloaded_skins(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ship,name,bundle,type FROM skins WHERE status='downloaded'"
        ).fetchall()
        return [{"ship": r[0], "name": r[1], "bundle": r[2], "type": r[3]} for r in rows]

    def close(self) -> None:
        self.conn.close()
