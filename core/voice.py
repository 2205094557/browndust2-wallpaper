"""BD2 角色互动语音：FEV+FSB5 语音包 → vgmstream 解码为 wav。

链路（国际服实测）：
  download_skin 下载 interaction_charXXXXXX bundle → 提取 TextAsset
    → resources/extracted/voice/{painting}/Interaction_CharXXXXXX
  → tools/probe_bd2_voice.decode_voice（定位 FSB5 魔数切片 → vgmstream 逐 stream）
    → resources/voice/{painting}/{cue}.wav

cue 名形如 Char003892_Int_{Mood}{N}_{variant}
（Smile/Sigh/Surprise/Pain/Eat/Neutral/Angry × 各 4 变体，共 64 条）。
前端播放 /api 静态 voice/{painting}/{cue}.wav，pick 按互动动作映射情绪组。
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "resources" / "extracted"
VOICE_DIR = ROOT / "resources" / "voice"  # {painting}/{cue}.wav
_PROBE_MOD = None

# 互动动作 → 情绪组（BD2 cue 的 {Mood} 段）
LABEL_MOODS = {
    "touch_head": ("Smile",),
    "touch_1": ("Neutral", "Smile"),
    "touch_2": ("Sigh", "Surprise"),
    "login": ("Smile", "Neutral"),
    "home": ("Neutral",),
}
MOOD_RE = re.compile(r"_Int_([A-Za-z]+)\d*_", re.I)


def _probe_module():
    """加载 tools/probe_bd2_voice.py（tools 无包结构，按路径加载）。"""
    global _PROBE_MOD
    if _PROBE_MOD is None:
        path = ROOT / "tools" / "probe_bd2_voice.py"
        spec = importlib.util.spec_from_file_location("_bd2_probe_voice", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PROBE_MOD = mod
    return _PROBE_MOD


def _bytes_file(painting: str) -> Path | None:
    d = EXTRACTED / "voice" / painting.lower()
    if not d.is_dir():
        return None
    for f in sorted(d.iterdir()):
        if f.name.lower().startswith("interaction_"):
            return f
    return None


def ship_id_for(painting: str) -> str | None:
    """painting → 语音 id（BD2 直接用服装 id；无语音资产返回 None）。"""
    p = (painting or "").lower()
    return p if re.fullmatch(r"char\d{6}", p) and _bytes_file(p) else None


# 复杂映射（如 illust_datingN → 所属服装 id）由 backend 注入：需要查元数据，
# 避免本模块反向依赖 Metadata。
_resolver = None


def set_resolver(fn) -> None:
    global _resolver
    _resolver = fn


def resolve_id(painting: str) -> str | None:
    """优先走注入的解析器（处理约会立绘等间接映射），失败回退直接匹配。"""
    p = (painting or "").lower()
    if _resolver:
        try:
            vid = _resolver(p)
            if vid:
                return vid
        except Exception:  # noqa: BLE001
            pass
    return ship_id_for(p)


def decoded_dir(painting: str) -> Path:
    return VOICE_DIR / painting.lower()


def voice_cues(painting: str) -> list[str]:
    """已解码的 cue 列表（wav 文件名去后缀）。"""
    d = decoded_dir(painting)
    if not d.is_dir():
        return []
    return sorted(f.stem for f in d.glob("*.wav"))


def ensure_decoded(painting: str, emit=None) -> bool:
    """把 extracted 里的 Interaction bytes 解码为 wav（幂等）。"""
    painting = (painting or "").lower()
    if not re.fullmatch(r"char\d{6}", painting):
        return False
    d = decoded_dir(painting)
    marker = d / ".done"
    if marker.exists():
        return True
    src = _bytes_file(painting)
    if src is None:
        return False
    if emit:
        emit("正在解码互动语音", detail=painting)
    mod = _probe_module()
    d.mkdir(parents=True, exist_ok=True)
    try:
        out = mod.decode_voice(str(src), str(d))
        ok = bool(out)
    except Exception as e:  # noqa: BLE001
        print(f"[voice] 解码失败 {painting}: {e}")
        ok = False
    if ok:
        marker.write_text("ok", encoding="utf-8")
    return ok


def pick_cue(painting: str, base: str, painting_arg: str | None = None) -> str | None:
    """互动动作 → 具体 cue。base ∈ touch_head/touch_1/touch_2/login/home。"""
    cues = voice_cues(painting)
    if not cues:
        return None
    moods = LABEL_MOODS.get(base, ("Neutral",))
    pool = [c for c in cues if (m := MOOD_RE.search(c)) and m.group(1).lower() in
            (x.lower() for x in moods)]
    if not pool:
        pool = cues
    # 同组多变体随机取一个（前端每次请求都拿最新 pick）
    import random

    return random.choice(pool) if pool else None


def words_for(painting: str) -> dict:
    """BD2 暂无台词文本数据源，返回空（前端字幕留空）。"""
    return {}


def download_voice(painting: str, info=None, cancel_event=None, emit=None) -> bool:
    """确保语音已就绪（bytes 下载在 download_skin 里完成，这里只补解码）。"""
    return ensure_decoded(painting, emit=emit)


def export_voice(painting: str, dest_dir: Path) -> dict | None:
    """把解码好的互动语音复制进壁纸项目，返回运行时配置。

    目标布局：dest_dir/{cue}.wav；配置 {"moods": {Smile:[cue,...]}}（BD2 互动
    引擎按区域情绪组运行时随机挑选），另保留 pick 兼容旧模板回退。
    无语音资产返回 None。
    """
    vid = resolve_id((painting or "").lower())
    if not vid:
        return None
    if not ensure_decoded(vid):
        return None
    cues = voice_cues(vid)
    if not cues:
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_dir = decoded_dir(vid)
    for cue in cues:
        shutil.copy2(src_dir / f"{cue}.wav", dest_dir / f"{cue}.wav")
    moods: dict[str, list[str]] = {}
    for cue in cues:
        m = MOOD_RE.search(cue)
        if m:
            key = m.group(1).capitalize()
            moods.setdefault(key, []).append(cue)
    pick = {}
    for base in LABEL_MOODS:
        cue = pick_cue(vid, base)
        if cue:
            pick[base] = cue
    return {"pick": pick, "moods": moods}


def remove_voice(painting: str) -> list[str]:
    """删除某服装的解码产物与源 bytes。"""
    removed = []
    for d in (decoded_dir(painting), EXTRACTED / "voice" / (painting or "").lower()):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(str(d))
    return removed


def clean_voice(keep: set | None = None) -> dict:
    """清理解码产物；keep 中的 painting 保留。"""
    keep = {k.lower() for k in (keep or set())}
    removed = 0
    if VOICE_DIR.is_dir():
        for d in VOICE_DIR.iterdir():
            if d.is_dir() and d.name.lower() not in keep:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    return {"removed": removed}
