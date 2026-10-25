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


def spine_skel_sets(d: Path) -> dict[str, str] | None:
    """多章约会皮的阶段骨架集（2026-10 实测 illust_dating22）。

    官方把每个章节场景做成独立骨架（illust_dating22_1=蜡烛人偶室 mix1 章、
    _2=影子场景 mix2 章），共享大包提取后全部落在基础目录。当目录内 skel 干名
    全部匹配 {目录名}_N 且成组（有同名 atlas）时，按卷号输出 {卷号: skel 名}；
    预览/壁纸据此只渲染当前阶段骨架，互动引擎按章节行走规则跨骨架推进。
    老目录（如 illust_dating1 里混入的 dating10~21 复制品，干名不含 _N 后缀）
    不满足全匹配条件，保持旧的多层叠加行为不变。
    """
    pairs = []
    for sk in sorted(d.glob("*.skel")):
        if not (d / (sk.stem + ".atlas")).exists():
            continue
        if not re.fullmatch(re.escape(d.name) + r"_\d+", sk.stem):
            return None
        pairs.append(sk)
    if len(pairs) < 2:
        return None
    out: dict[str, str] = {}
    for sk in pairs:
        out[str(int(sk.stem.rsplit("_", 1)[1]))] = sk.name
    return out


def _bg_candidates(d: Path) -> list[Path]:
    """cutscene 独立背景贴图候选（back*/bg* 系列；角色贴图/glow 等排除）。"""
    cands = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".png":
            continue
        low = f.name.lower()
        if low.startswith("cutscene_") or low.startswith("glow"):
            continue
        # 只考虑 back* 或 bg* 系列（分隔符 _ / 空格 - 均可）；bg 后可无分隔直接跟
        # 数字（实测 char003793/char067902 演出包为 CharrNNNNNN_bg1 命名）
        if re.search(r"(?:^|[_ -])back\d*|(?:^|[_ -])bg(?:[_ -]*\d+|_)", low):
            cands.append(f)
    return cands


def _bg_quality(f: Path) -> tuple[int, float]:
    """背景质量度量：(面积, 不透明占比)——完整背景大而实心，装饰层小/透明。"""
    from PIL import Image

    img = Image.open(f).convert("RGBA")
    w, h = img.size
    px = img.load()
    opaque = total = 0
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            total += 1
            if px[x, y][3] > 128:
                opaque += 1
    return (w * h, opaque / total if total else 0)


def _bg_set_token(low: str) -> int | None:
    """背景组编号：back 后的数字（back1/back1-1/back_01/back 2 → 各自组号）。

    无数字（bg_flower 等装饰/叠加件）返回 None，不当作阶段背景。
    """
    m = re.search(r"(?:back|bg)[_ -]*(\d+)", low)
    return int(m.group(1)) if m else None


def spine_bg_sets(d: Path) -> dict[str, str]:
    """按组号提取全部阶段背景：{组号: 该组里最大最实心的图}。

    Ultimate 演出每个阶段（loop/cut 段）配一组独立背景（back1..backN，
    组内 -1/-2 等是同阶段分层/变体），此前只挑一张导致其余阶段背景缺失。
    组号排序输出；无数字命名的装饰层（bg_flower 等）排除。
    """
    groups: dict[int, list[Path]] = {}
    for f in _bg_candidates(d):
        tok = _bg_set_token(f.name.lower())
        if tok is None:
            continue
        groups.setdefault(tok, []).append(f)

    out: dict[str, str] = {}
    for tok in sorted(groups):
        files = groups[tok]
        if not files:
            continue
        # 基底名（backN.png，无 -N/…变体后缀）优先当该阶段背景；没有基底再从变体里选
        base = [f for f in files if re.search(r"(?:back|bg)[_ -]*\d+\.png$", f.name.lower())]
        pool = base or files
        best, best_q = pool[0], (-1, -1.0)
        for f in pool:
            try:
                q = _bg_quality(f)
                if q > best_q:
                    best_q, best = q, f
            except Exception:  # noqa: BLE001
                continue
        out[str(tok)] = best.name
    return out


def spine_bg(d: Path) -> str | None:
    """从提取目录中检测 cutscene 的完整背景图（独立贴图，不在 Spine 骨架/atlas 内）。

    命名实测极不一致：back1 / back 1 / -back1 / back_01 / bg_01 / back10 /
    back1_1..N / back2_1..N 等。统一启发式：在 back*/bg* 候选里选
    「面积最大 + 不透明占比最高 + 名称排序最前」——完整背景都是大而实心的整幅
    场景；装饰层（glow/feathers/flower/小贴纸）要么小、要么透明占比高。
    """
    from PIL import Image

    cands = _bg_candidates(d)
    if not cands:
        return None

    best, best_key = None, (-1, -1.0, -1)
    for idx, f in enumerate(cands):
        try:
            area, ratio = _bg_quality(f)
            key = (area, ratio, -idx)  # 同面积同透明度时取排序最前的
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
            skel_sets = spine_skel_sets(d)
            if skel_sets:
                # 阶段骨架集随 asset 记录（多章约会皮，2026-10 dating22 起）：
                # 预览/壁纸只渲染当前阶段骨架，互动引擎按章节行走规则跨阶段推进
                asset["skel_sets"] = skel_sets
            bg_sets = spine_bg_sets(d)
            if bg_sets:
                # 全部阶段背景随 asset 记录（导出/预览按动画切换背景用）
                asset["bg_sets"] = bg_sets
                # 默认背景层 = 组 1（default 动画/首阶段），预览/模板保持既有渲染路径
                default_bg = bg_sets.get("1") or bg_sets[sorted(bg_sets)[0]]
                asset["layers"].append({"bg": default_bg})
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
    # 拼音索引带上本地条目名（覆盖 skins.json 未含的本地命名变体）
    build_pinyin_index(skins + [{"name": l["name"]} for l in local])
    print("local_skins:", len(local))
    for l in local:
        print(" ", l["ship"], "|", l["bundle"], "|", l["name"], "|", l["type"], "|", l["asset"]["dir"])


if __name__ == "__main__":
    main()
