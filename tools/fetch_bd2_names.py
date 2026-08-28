# -*- coding: utf-8 -*-
"""从 BD2DB（browndust2-db.souseha.com）同步角色/皮肤中文名与头像。

数据源结构（Vue SPA，数据在构建产物 JS 块里，随版本换 hash）：
  /cn/skins 页面 HTML → main-*.js 入口名
  main js        → import("./loadCharacters-*.js")
  loadCharacters → from"./db-characters-*.js"（真正的数据库，~2.6MB）
块内三段结构（2026-08 实测，键序固定）：
  服装主表  {costumeId:"Morpeah_2",character:"墨菲亞",costumeName:"白日夢兔女郎",
             characterId:"Morpeah",... gameId:"003402",avatarId:"003402",...}
  角色i18n  {characterId:"Morpeah",character:"墨菲亞",character_CN:"墨菲亚",character_en:"Morpeah",...}
  皮肤i18n  {costumeId:"Morpeah_2",... costumeName_CN:"白日梦兔女郎",costumeName_en:"Daydream Bunny",...}
gameId 与本仓库的服装 6 位 id（charXXXXXX）完全一致，可直接对齐。
头像：https://image-bd2db.souseha.com/avatar/icon_char{avatarId}.webp

产物（resources/metadata/）：
  - bd2db_names.json   角色/皮肤中英文名映射（build_bd2_metadata.py 消费）
  - avatars.json       中文角色名 -> 头像文件名（前端图鉴直接读取）
  - ../avatars/{名}.jpg 头像图片（webp 转白底 JPEG）

用法：
  python tools/fetch_bd2_names.py            # 联网同步（头像已有且未变则跳过）
  python tools/fetch_bd2_names.py --force    # 强制重下全部头像
  python tools/fetch_bd2_names.py --offline  # 只用本地缓存的 db 块重新解析
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "resources" / "metadata"
AVATAR_DIR = ROOT / "resources" / "avatars"
AVATAR_MAP = MD / "avatars.json"
NAMES_OUT = MD / "bd2db_names.json"
CACHE_JS = MD / "bd2db_dbcache.js"

SITE = "https://browndust2-db.souseha.com"
IMAGE_HOST = "https://image-bd2db.souseha.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_ATTEMPTS = 3


def _get(url: str, timeout=(15, 60)) -> bytes:
    last = None
    for attempt in range(_ATTEMPTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < _ATTEMPTS - 1:
                time.sleep(1 + attempt * 2)
    raise RuntimeError(f"GET {url} 失败: {last}")


# ---- 发现并下载数据库块 -----------------------------------------------------

_RE_MAIN = re.compile(r'(/assets/main-[A-Za-z0-9_-]+\.js)')
_RE_LOADCHARS = re.compile(r'"\./(loadCharacters-[A-Za-z0-9_-]+\.js)"')
_RE_DBCHUNK = re.compile(r'from"\./(db-characters-[A-Za-z0-9_-]+\.js)"')


def resolve_db_chunk_url() -> tuple[str, bytes]:
    """HTML → main js → loadCharacters 块 → db-characters 块 URL。"""
    html = _get(f"{SITE}/cn/skins").decode("utf-8", "replace")
    m = _RE_MAIN.search(html)
    if not m:
        raise RuntimeError("页面里找不到 main-*.js 入口")
    main_js = _get(f"{SITE}{m.group(1)}").decode("utf-8", "replace")
    m = _RE_LOADCHARS.search(main_js)
    if not m:
        raise RuntimeError("main js 里找不到 loadCharacters 块")
    loader = _get(f"{SITE}/assets/{m.group(1)}").decode("utf-8", "replace")
    m = _RE_DBCHUNK.search(loader)
    if not m:
        raise RuntimeError("loadCharacters 里找不到 db-characters 块")
    url = f"{SITE}/assets/{m.group(1)}"
    return url, _get(url)


# ---- 解析（纯正则：字段键序固定、值不含未转义引号） -------------------------

_RE_COSTUME = re.compile(
    r'\{costumeId:"([A-Za-z0-9_]+)",character:"([^"]*)",costumeName:"([^"]*)",characterId:"([A-Za-z0-9_]+)"')
_RE_GAMEID = re.compile(r'gameId:"(\d{6})",avatarId:"(\d{6})"')
_RE_CHAR_I18N = re.compile(
    r'\{characterId:"([A-Za-z0-9_]+)",character:"([^"]*)",character_CN:"([^"]*)",character_en:"([^"]*)"')
_RE_SKIN_I18N = re.compile(
    r'\{costumeId:"([A-Za-z0-9_]+)",character:"[^"]*",costumeName:"[^"]*",'
    r'costumeName_CN:"([^"]*)",costumeName_en:"([^"]*)"')


def parse_db_chunk(text: str) -> dict:
    costumes: dict[str, dict] = {}   # gameId(6位) -> 记录
    chars: dict[str, dict] = {}      # characterId -> i18n 名
    skin_i18n: dict[str, dict] = {}  # costumeId -> i18n 名
    for m in _RE_COSTUME.finditer(text):
        window_end = min(m.end() + 9000, len(text))
        gm = _RE_GAMEID.search(text, m.end(), window_end)
        if not gm:
            continue
        costumes[gm.group(1)] = {
            "costume_id": m.group(1),
            "character_id": m.group(4),
            "name_tc": m.group(3),
            "char_tc": m.group(2),
            "avatar_id": gm.group(2),
        }
    for m in _RE_CHAR_I18N.finditer(text):
        chars[m.group(1)] = {"tc": m.group(2), "cn": m.group(3), "en": m.group(4)}
    for m in _RE_SKIN_I18N.finditer(text):
        skin_i18n[m.group(1)] = {"cn": m.group(2), "en": m.group(3)}
    if not costumes or not chars:
        raise RuntimeError(f"解析结果为空（costumes={len(costumes)} chars={len(chars)}），站点结构可能已变更")
    # 补齐皮肤简体/英文名
    for rec in costumes.values():
        i18n = skin_i18n.get(rec["costume_id"]) or {}
        rec["name_cn"] = i18n.get("cn") or rec["name_tc"]
        rec["name_en"] = i18n.get("en") or ""
        ci = chars.get(rec["character_id"]) or {}
        rec["char_cn"] = ci.get("cn") or rec["char_tc"]
        rec["char_en"] = ci.get("en") or ""
    return {"characters": chars, "costumes": costumes}


# ---- 头像 -------------------------------------------------------------------

def safe_filename(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r'[\\/:*?"<>|\s]+', "", s).strip(".")


def download_avatars(data: dict, force: bool = False) -> dict:
    """按角色下载代表头像（选该角色最小的 gameId），返回 avatars.json 映射。

    按 characterId 选图但以中文角色名落盘；中文重名的角色只取第一个，
    避免文件互相覆盖。
    """
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    fp_path = MD / "bd2db_avatar_fp.json"
    try:
        fp = json.loads(fp_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        fp = {}

    # 每个角色选一个代表服装（id 最小者）
    best: dict[str, dict] = {}
    for game_id, rec in data["costumes"].items():
        cid = rec["character_id"]
        cur = best.get(cid)
        if cur is None or int(game_id) < int(cur["game_id"]):
            best[cid] = {**rec, "game_id": game_id}

    mapping: dict[str, str] = {}
    seen_cn: set[str] = set()
    ok = fail = skip = 0
    for cid in sorted(best, key=lambda c: int(best[c]["game_id"])):
        rec = best[cid]
        cn = (rec["char_cn"] or "").strip()
        fname_base = safe_filename(cn)
        if not cn or not fname_base or fname_base in seen_cn:
            continue
        seen_cn.add(fname_base)
        url = f"{IMAGE_HOST}/avatar/icon_char{rec['avatar_id']}.webp"
        dest = AVATAR_DIR / f"{fname_base}.jpg"
        prev = fp.get(cid) or {}
        if not force and dest.exists() and prev.get("url") == url:
            skip += 1
        else:
            try:
                raw = _get(url, timeout=(15, 30))
                _webp_to_jpg(raw, dest)
                fp[cid] = {"url": url, "avatar_id": rec["avatar_id"], "file": dest.name}
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"[warn] 头像下载失败 {cn}: {e}")
        if dest.exists():
            mapping[cn] = fname_base
    fp_path.write_text(json.dumps(fp, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"mapping": mapping, "downloaded": ok, "skipped": skip, "failed": fail}


def _webp_to_jpg(raw: bytes, dest: Path) -> None:
    from io import BytesIO

    from PIL import Image
    img = Image.open(BytesIO(raw))
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    tmp = dest.with_suffix(".jpg.part")
    img.save(tmp, "JPEG", quality=90)
    tmp.replace(dest)


# ---- 主流程 -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="强制重下所有头像")
    ap.add_argument("--offline", action="store_true", help="只用本地缓存的 db 块解析（不联网）")
    args = ap.parse_args()

    t0 = time.time()
    online_err = ""
    fetched_url = ""
    if not args.offline:
        try:
            fetched_url, raw = resolve_db_chunk_url()
            CACHE_JS.write_bytes(raw)
        except Exception as e:  # noqa: BLE001
            online_err = str(e)
            if not CACHE_JS.exists():
                print(f"[error] 在线获取失败且无本地缓存：{online_err}")
                raise SystemExit(1)
            print(f"[warn] 在线获取失败，回退本地缓存：{online_err}")
    elif not CACHE_JS.exists():
        print("[error] --offline 但没有本地缓存，请先联网运行一次")
        raise SystemExit(1)

    text = CACHE_JS.read_text(encoding="utf-8", errors="replace")
    data = parse_db_chunk(text)

    ava = download_avatars(data, force=args.force)
    (MD / "avatars.json").write_text(
        json.dumps(ava["mapping"], ensure_ascii=False, indent=1), encoding="utf-8")

    out = {
        "source": "browndust2-db.souseha.com",
        "chunk_url": fetched_url or "(cached)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "characters": data["characters"],
        "costumes": data["costumes"],
    }
    NAMES_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    n_cn = sum(1 for c in data["costumes"].values() if c["name_cn"])
    print("=" * 60)
    print(f"BD2DB 名称/头像同步完成（{time.time() - t0:.1f}s）")
    print(f"chunk        : {out['chunk_url']}")
    print(f"costumes     : {len(data['costumes'])}（有简体名 {n_cn}）")
    print(f"characters   : {len(data['characters'])}")
    print(f"avatars      : 下载 {ava['downloaded']} / 跳过 {ava['skipped']} / 失败 {ava['failed']}"
          f"，映射 {len(ava['mapping'])}")
    if online_err:
        print(f"[!] 本次在线更新失败（用了缓存）：{online_err}")
        raise SystemExit(2)
    print("=" * 60)


if __name__ == "__main__":
    main()
