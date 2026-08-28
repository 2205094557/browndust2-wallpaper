"""Build BD2 character metadata from the community character table + official asset catalog.

Inputs (paths are optional CLI args, defaulting to the constants below):
  - character_list.ts   BD2-L2D-Viewer community table (TS/JSON hybrid, ~224 costumes)
  - assets.tsv          official catalog asset key list, `asset_key<TAB>dep_index` (40万行)

Outputs under resources/metadata/:
  - characters.json  one entry per costume id with asset capability flags
  - ships.json       per-character aggregation (grouped by charName, deduped)

Usage:
  python tools/build_bd2_metadata.py [--character-list PATH] [--assets PATH]

Asset keys are matched case-insensitively (catalog mixes Char003892 / char003892).
IDs seen in assets (illust_char<id>_<n>.prefab) but missing from character_list.ts
are appended as unknown entries (char/costume = "Unknown").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
METADATA_DIR = ROOT / "resources" / "metadata"

# Input defaults -- absolute paths into the research dump. Adjust here when relocated.
DEFAULT_CHARACTER_LIST = Path(r"D:\codex\_bd2_research\character_list.ts")
DEFAULT_ASSETS_TSV = Path(r"D:\codex\_bd2_research\assets.tsv")

NAMES_JSON = METADATA_DIR / "bd2db_names.json"  # fetch_bd2_names.py 产物


def resolve_assets_tsv(cli_value: str | None) -> Path:
    """资产目录优先级：CLI 参数 > 本地最新的 CDN catalog 缓存 > 研究目录快照。

    缓存由后端按需更新（cdn.catalog_csv），用上它重建即可收录新角色服装；
    研究目录快照只是兜底。
    """
    if cli_value:
        return Path(cli_value)
    cached = sorted(METADATA_DIR.glob("bd2_catalog_HD_*.tsv"))
    if cached:
        return cached[-1]
    return DEFAULT_ASSETS_TSV

SORT_FALLBACK = 9999  # 图鉴序号 unavailable -> large number so it sorts last

# --- asset-key patterns (all applied to lower-cased keys) -------------------

# UI/Prefabs/Spine/IllustSpine/illust_char003892_190.prefab  (+ Censorship/ subpath)
_RE_SPINE = re.compile(r"illust_char(\d+)_(\d+)\.prefab$")
# Illust_1/illust_char003892_190.png
_RE_STATIC = re.compile(r"illust_char(\d+)_(\d+)\.png$")
# SkeletonData/cutscene_char003892/...
_RE_CUTSCENE = re.compile(r"skeletondata/cutscene_char(\d+)/")
# BundleInteractionVoice/Interaction_Char003892.bytes  or the bundle manifest form
# ..._assets_bundleinteractionvoice/interaction_char003892.bytes_<hash>.bundle
_RE_VOICE = re.compile(r"interaction_char(\w+)\.bytes")
# Char/Datingillust/Illust_dating14.prefab  (Censorship/ subpath is an acceptable fallback)
_RE_DATING = re.compile(r"char/datingillust/(?:censorship/)?illust_dating(\d+)\.prefab$")


class AssetIndex:
    """Precomputed indexes over the asset catalog for fast per-id lookups."""

    def __init__(self) -> None:
        self.spine: dict[str, tuple[int, str]] = {}  # id -> (图鉴序号, original key)
        self.static: dict[str, tuple[int, str]] = {}  # id -> (max number, original key)
        self.cutscene: set[str] = set()
        self.voice: set[str] = set()
        self.dating: set[str] = set()  # "illust_dating14"-style names with a prefab
        self.special: list[tuple[str, str]] = []  # (low key, original key) under IllustSpecial/
        self._special_seen: set[str] = set()


def index_assets(tsv_path: Path) -> AssetIndex:
    idx = AssetIndex()
    with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line or line == "\n":
                continue
            key = line.split("\t", 1)[0]
            low = key.lower()

            if low.startswith("ui/prefabs/spine/illustspine/"):
                m = _RE_SPINE.search(low)
                if m:
                    uid, num = m.group(1), int(m.group(2))
                    cur = idx.spine.get(uid)
                    if cur is None or num > cur[0]:
                        idx.spine[uid] = (num, key)
                    continue
                # special / skeleton dirs are not nested under illustspine, so no else needed
            elif low.startswith("illust_1/"):
                m = _RE_STATIC.search(low)
                if m:
                    uid, num = m.group(1), int(m.group(2))
                    cur = idx.static.get(uid)
                    if cur is None or num > cur[0]:
                        idx.static[uid] = (num, key)
                    continue
            elif low.startswith("skeletondata/cutscene_char"):
                m = _RE_CUTSCENE.match(low)
                if m:
                    idx.cutscene.add(m.group(1))
                    continue
            elif low.startswith("ui/prefabs/spine/illustspecial/"):
                if low not in idx._special_seen:
                    idx._special_seen.add(low)
                    idx.special.append((low, key))
                continue

            m = _RE_VOICE.search(low)
            if m:
                idx.voice.add(m.group(1))
                continue
            m = _RE_DATING.match(low)
            if m:
                idx.dating.add(f"illust_dating{m.group(1)}")
    return idx


def load_character_list(ts_path: Path) -> dict:
    """Strip the TS wrapper ('export default {...} as {...}') and parse as JSON."""
    text = ts_path.read_text(encoding="utf-8-sig")
    head_marker = "export default"
    if head_marker in text:
        text = text.split(head_marker, 1)[1]
    trailer_marker = " as {"
    if trailer_marker in text:
        text = text.split(trailer_marker, 1)[0]
    return json.loads(text)


def pick_special_prefab(uid: str, special: list[tuple[str, str]]) -> str:
    """Pick the best IllustSpecial key containing this char id.

    Candidates must contain the 6-digit id. Ranking: .prefab over .playable,
    non-Censorship over Censorship, shortest basename (= main variant, no
    _loop/_2 suffixes) first, then first-seen order. Returns "" when absent;
    the returned key keeps the original catalog casing.
    """
    cands = []
    for low, orig in special:
        if uid in low:
            cands.append((low, orig))
    if not cands:
        return ""
    censored = "/censorship/" in low

    def rank(item):
        lowkey, _ = item
        basename = lowkey.rsplit("/", 1)[1]
        return (
            0 if lowkey.endswith(".prefab") else 1,
            1 if censored else 0,
            len(basename),
        )

    return min(cands, key=rank)[1]


def asset_uid(uid: str, meta: dict | None) -> str:
    """Resolve the asset-side id: censored variants (_c) share the base costume's assets."""
    if uid.endswith("_c"):
        icon = (meta or {}).get("icon")
        if icon:
            return icon
        return uid[:-2]
    return uid


def build_entry(uid: str, meta: dict, assets: AssetIndex) -> dict:
    base = asset_uid(uid, meta).zfill(6)
    spine = assets.spine.get(base)
    static = assets.static.get(base)
    has_cutscene = base in assets.cutscene

    dating = meta.get("dating") or ""
    if dating:
        m = re.fullmatch(r"illust_dating(\d+)", dating)
        if not m or f"illust_dating{m.group(1)}" not in assets.dating:
            dating = ""  # community table claims dating but the prefab is not in the catalog

    return {
        "id": uid,
        "char": meta.get("charName") or "Unknown",
        "costume": meta.get("costumeName") or "Unknown",
        "spine": meta.get("spine") or f"char{base}",
        "dating": dating,
        "cutscene": f"cutscene_char{base}" if has_cutscene else (meta.get("cutscene") or ""),
        "special": "",  # v1: SpecialIllustN <-> char mapping has no reliable source
        "special_prefab": pick_special_prefab(base, assets.special),
        "voice": base in assets.voice,
        "static": static[1] if static else "",
        "sort": spine[0] if spine else SORT_FALLBACK,
    }


def build_unknown_entry(uid: str, assets: AssetIndex) -> dict:
    spine = assets.spine.get(uid)
    static = assets.static.get(uid)
    return {
        "id": uid,
        "char": "Unknown",
        "costume": "Unknown",
        "spine": f"char{uid}",
        "dating": "",
        "cutscene": f"cutscene_char{uid}" if uid in assets.cutscene else "",
        "special": "",
        "special_prefab": pick_special_prefab(uid, assets.special),
        "voice": uid in assets.voice,
        "static": static[1] if static else "",
        "sort": spine[0] if spine else SORT_FALLBACK,
    }


def build_ships(entries: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(e["char"], []).append(e)
    ships = []
    for name, members in groups.items():
        costumes = sorted(m["id"] for m in members)
        en = next((m.get("char_en") for m in members if m.get("char_en")), "")
        ships.append({"name": name, "en": en, "costumes": costumes,
                      "sort": min(m["sort"] for m in members)})
    ships.sort(key=lambda s: (s["sort"], s["name"]))
    return ships


def load_cn_names() -> dict:
    """fetch_bd2_names.py 的产物；缺失/损坏时返回空映射（保持英文名可用）。"""
    try:
        data = json.loads(NAMES_JSON.read_text(encoding="utf-8"))
        return {k: v for k, v in (data.get("costumes") or {}).items()
                if isinstance(v, dict) and isinstance(k, str)}
    except Exception:  # noqa: BLE001
        return {}


def apply_cn_names(entries: list[dict], cn_by_id: dict) -> tuple[int, int]:
    """按 6 位服装 id 叠加 BD2DB 简体中文名，返回（角色改名数, 皮肤改名数）。

    中文名缺失时保留原名；原英文名存入 char_en/costume_en 供检索与排序。
    角色名按「原英文名」投票后整组统一：BD2DB 常只收录角色新服装，
    若逐服装改名会把同一角色裂成中/英两个图鉴条目、头像也跟丢。
    """
    votes: dict[str, str] = {}
    for e in entries:
        rec = cn_by_id.get(e["id"])
        if rec:
            cn = (rec.get("char_cn") or "").strip()
            if cn:
                votes.setdefault(e["char"], cn)

    char_n = skin_n = 0
    for e in entries:
        if e.get("char_en") is None:
            e["char_en"] = e["char"]
        if e.get("costume_en") is None:
            e["costume_en"] = e["costume"]
        cn_char = votes.get(e["char_en"], "").strip()
        if cn_char and cn_char != e["char"]:
            e["char"] = cn_char
            char_n += 1
        rec = cn_by_id.get(e["id"])
        cn_cost = (rec or {}).get("name_cn", "").strip()
        if cn_cost and cn_cost != e["costume"]:
            e["costume"] = cn_cost
            skin_n += 1
    return char_n, skin_n


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--character-list", default=str(DEFAULT_CHARACTER_LIST), help="path to character_list.ts")
    ap.add_argument("--assets", default=None, help="assets/catalog TSV（缺省自动选最新 CDN 缓存）")
    args = ap.parse_args()
    assets_path = resolve_assets_tsv(args.assets)

    t0 = time.time()
    char_list = load_character_list(Path(args.character_list))
    assets = index_assets(assets_path)

    entries = []
    known_ids = set(char_list)
    for uid, meta in char_list.items():
        entries.append(build_entry(uid, meta, assets))

    unknown_ids = sorted(set(assets.spine) - known_ids)
    for uid in unknown_ids:
        entries.append(build_unknown_entry(uid, assets))

    cn_by_id = load_cn_names()
    char_n, skin_n = apply_cn_names(entries, cn_by_id)

    ships = build_ships(entries)

    char_path = METADATA_DIR / "characters.json"
    ships_path = METADATA_DIR / "ships.json"
    write_json(char_path, entries)
    write_json(ships_path, ships)

    # ---- stats report ------------------------------------------------------
    def count(pred):
        return sum(1 for e in entries if pred(e))

    with_spine = count(lambda e: e["sort"] != SORT_FALLBACK)
    with_dating = count(lambda e: bool(e["dating"]))
    with_cutscene = count(lambda e: bool(e["cutscene"]))
    with_voice = count(lambda e: e["voice"])
    with_static = count(lambda e: bool(e["static"]))
    liberta = [e for e in entries if e["id"] in {"003801", "003802", "003803", "003892"}]

    print("=" * 60)
    print("BD2 metadata build report")
    print("=" * 60)
    print(f"character_list : {args.character_list}")
    print(f"assets.tsv     : {assets_path}")
    print(f"cn_names       : {NAMES_JSON.name}（{len(cn_by_id)} 条，角色改名 {char_n} / 皮肤改名 {skin_n}）")
    print(f"elapsed        : {time.time() - t0:.2f}s")
    print("-" * 60)
    print(f"characters.json: {len(entries)} entries "
          f"({len(char_list)} from community table + {len(unknown_ids)} appended Unknown)")
    print(f"  with spine   : {with_spine}")
    print(f"  with dating  : {with_dating}")
    print(f"  with cutscene: {with_cutscene}")
    print(f"  with voice   : {with_voice}")
    print(f"  with static  : {with_static}")
    print(f"ships.json     : {len(ships)} characters")
    print("-" * 60)
    if unknown_ids:
        print(f"Unknown appended ids ({len(unknown_ids)}): {', '.join(unknown_ids)}")
    else:
        print("Unknown appended ids: 0")
    print("-" * 60)
    print("Liberta quartet (003801 / 003802 / 003803 / 003892):")
    print(json.dumps(liberta, ensure_ascii=False, indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()