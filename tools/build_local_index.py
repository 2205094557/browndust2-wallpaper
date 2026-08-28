# -*- coding: utf-8 -*-
"""扫描 resources/extracted → 生成 local_skins.json（BD2 版）。

BD2 每个皮肤条目（主立绘/约会/尊爵/演出）都是**单一骨架**，没有碧蓝的
_T/_B/_M 多部件结构，也不需要图层合并——直接 skel+atlas 成组即可。
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
EXTRACTED = ROOT / "resources" / "extracted"


def spine_asset(d: Path) -> dict | None:
    """目录里找 skel+atlas 成组的主骨架（BD2 单骨架；多 skel 时取附件最多组的第一个）。"""
    pairs = []
    for sk in sorted(d.glob("*.skel")):
        atlas = d / (sk.stem + ".atlas")
        if atlas.exists():
            pairs.append({"skel": sk.name, "atlas": atlas.name})
    if not pairs:
        return None
    return {"dir": "extracted/spine/" + d.name, "layers": pairs}


def spine_bg(d: Path) -> str | None:
    """从提取目录中检测 cutscene 的完整背景图（独立贴图，不在 Spine 骨架/atlas 内）。

    命名实测极不一致：back1 / back 1 / -back1 / back_01 / bg_01 / back10 /
    back1_1..N / back2_1..N 等。统一启发式：在 back*/bg* 候选里选
    「面积最大 + 不透明占比最高 + 名称排序最前」——完整背景都是大而实心的整幅
    场景；装饰层（glow/feathers/flower/小贴纸）要么小、要么透明占比高。
    """
    from PIL import Image

    cands = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".png":
            continue
        low = f.name.lower()
        # 角色贴图（cutscene_char*.png / *_N.png）与通用特效（glow）不参与
        if low.startswith("cutscene_") or low.startswith("glow"):
            continue
        # 只考虑 back* 或 bg* 系列（分隔符 _ / 空格 / - 均可）
        if re.search(r"(?:^|[_ -])back\d*|(?:^|[_ -])bg_", low):
            cands.append(f)
    if not cands:
        return None

    best, best_key = None, (-1, -1, -1)
    for idx, f in enumerate(cands):
        try:
            img = Image.open(f).convert("RGBA")
            w, h = img.size
            px = img.load()
            opaque = total = 0
            for y in range(0, h, 8):  # 1/64 抽样不透明占比
                for x in range(0, w, 8):
                    total += 1
                    if px[x, y][3] > 128:
                        opaque += 1
            ratio = opaque / total if total else 0
            key = (w * h, ratio, -idx)  # 同面积同透明度时取排序最前的
            if key > best_key:
                best_key, best = key, f.name
        except Exception:  # noqa: BLE001
            continue
    return best


def build_pinyin_index(skins: list[dict]) -> None:
    """生成检索索引 pinyin.json。

    BD2 名字已本地化为中文：p 字段 = 中文名全拼 + 英文名原串（均可搜），
    i = 首字母；角色级并入 char_en，皮肤后缀「· 约会」等不参与索引。
    """
    try:
        ships = json.loads((MD / "ships.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ships = []

    def py_of(text: str) -> str:
        if not text:
            return ""
        try:
            from pypinyin import lazy_pinyin
            return "".join(lazy_pinyin(text)).lower()
        except Exception:  # noqa: BLE001  无 pypinyin 时退化为原名
            return ""

    def key_of(*names: str) -> dict:
        cn_heads: list[str] = []
        latins: list[str] = []
        for n in names:
            n = (n or "").strip()
            if not n:
                continue
            head = n.split("·", 1)[0]  # 去掉「· 约会」等能力后缀
            if any("\u4e00" <= ch <= "\u9fff" for ch in head):
                cn_heads.append(head)
            else:
                latins.append("".join(ch for ch in head.lower() if ch.isalnum()))
        pys = [py_of(h) for h in cn_heads]
        p = "".join(pys) + "".join(latins)
        i = "".join(x[:1] for x in pys) + "".join(l[:1] for l in latins if l)
        return {"p": p[:64], "i": i[:16] or p[:8]}

    ships_map = {}
    for s in ships:
        nm = s.get("name", "")
        if nm:
            ships_map[nm] = key_of(nm, s.get("en", ""))
    skins_map: dict[str, dict] = {}
    for sk in skins:
        n = sk.get("name", "")
        if n and n not in skins_map:
            skins_map[n] = key_of(n)
    (MD / "pinyin.json").write_text(
        json.dumps({"ships": ships_map, "skins": skins_map}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def main():
    skins = json.loads((MD / "skins.json").read_text(encoding="utf-8"))
    by_painting = {}
    for s in skins:
        p = s.get("painting", "")
        if p and p not in by_painting:
            by_painting[p] = s

    local = []

    # spine 目录：主立绘/约会/尊爵/演出统一在此（单骨架）
    spine_dir = EXTRACTED / "spine"
    if spine_dir.is_dir():
        for d in sorted(spine_dir.iterdir()):
            if not d.is_dir():
                continue
            info = by_painting.get(d.name)
            if not info:
                continue
            asset = spine_asset(d)
            if not asset:
                continue
            bg = spine_bg(d)
            if bg:
                # 独立背景图作为 bg layer：预览 loadBg/drawBg 与壁纸模板都会渲染
                asset["layers"].append({"bg": bg})
            local.append({
                "ship": info["ship"], "bundle": info["bundle"], "name": info["name"],
                "type": "spine", "painting": info.get("painting", d.name),
                "asset": asset,
            })

    # 静态立绘目录
    static_dir = EXTRACTED / "static"
    if static_dir.is_dir():
        for d in sorted(static_dir.iterdir()):
            if not d.is_dir():
                continue
            info = by_painting.get(d.name)
            if not info:
                continue
            png = d / "painting.png"
            if not png.exists():
                continue
            local.append({
                "ship": info["ship"], "bundle": info["bundle"], "name": info["name"],
                "type": "static",
                "painting": info.get("painting", ""),
                "asset": {"dir": f"extracted/static/{d.name}", "image": "painting.png"},
            })

    local.sort(key=lambda x: (x["ship"], x["bundle"]))
    (MD / "local_skins.json").write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    build_pinyin_index(skins)
    print("local_skins:", len(local))
    for l in local:
        print(" ", l["ship"], "|", l["bundle"], "|", l["name"], "|", l["type"], "|", l["asset"]["dir"])


if __name__ == "__main__":
    main()
