#!/usr/bin/env python3
"""BD2（棕色尘埃2）互动语音包格式探测与解码验证脚本。

调研结论（2026，Interaction_Char003892 实测）：
  - Unity TextAsset 里的互动语音包不是 CriWare（ACB/HCA），也不是 Wwise（bnk/wem），
    而是 **FMOD Designer 烘焙的 FEV+FSB5 容器**：
        RIFF form="FEV " -> FMT + LIST("PROJ"+"BNKI" 配置) + SND(内嵌 "FSB5" 采样银行)
  - FSB5 采样银行：version=1（Designer 变体），64 个 sample，编码 **FMOD FADPCM 4-bit ADPCM**，
    48kHz 单声道；sample 名即 cue 名（如 Char003892_Int_Sigh1_3）。
  - vgmstream 的 FEV+FSB5 .bank 支持只覆盖 FSB5 藏在 BNKI/SNDH 里的变体；
    本包 FSB5 直接内嵌在顶层 SND 块，所以先按 "FSB5" 魔数切片成 .fsb 再喂 vgmstream。
  - 解码路径：切片 FSB5 -> vgmstream-cli 逐 stream 解出 {cue}.wav（实测 64/64 成功）。

用法:
  python tools/probe_bd2_voice.py <bytes文件>                     # 只输出格式判定 JSON
  python tools/probe_bd2_voice.py <bytes文件> --decode            # 判定 + 解码
  python tools/probe_bd2_voice.py <bytes文件> --decode --out DIR [--vgmstream DIR]

约束（项目铁律，见 AGENTS.md / core/voice.py）:
  - vgmstream 调用必须 creationflags=CREATE_NO_WINDOW
    + encoding='utf-8', errors='replace'（cue 名可能是非 GBK 编码）
  - 临时 .fsb 副本用完即删（finally），不残留
  - 仅用标准库，不新装依赖
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# BD2 互动语音 TextAsset 容器结构（实测魔数）
RIFF_MAGICS = {
    b"RIFF": "RIFF (A/V container)",
    b"FSB5": "FMOD FSB5 Level-5 sample bank",
    b"FSB4": "FMOD FSB4 sample bank",
    b"OggS": "Ogg container",
    b"fLaC": "FLAC",
    b"ID3": "MP3 ID3 tag",
    b"BKHD": "Wwise SoundBank",
    b"AKPK": "Wwise package",
    b"CRID": "CriWare CRI",
    b"@UTF": "CriWare UTF container",
    b"UnityFS": "Unity AssetBundle",
    b"OpusHead": "Opus",
    b"FORM": "IFF/AIFF container",
}
# cue 名形态：Char{角色id}_Int_{情绪}{序号}_{变体}
CUE_NAME_RE = re.compile(rb"Char\d+_Int_[A-Za-z]+\d+_\d+")
# 顶层 RIFF 子块（4 字节块 id），用于容器说明
KNOWN_RIFF_SUBCHUNKS = (b"FMT ", b"LIST", b"SND ", b"BNKI", b"PROJ")


def _default_vgmstream_dir() -> Path:
    """优先用本仓库 tools/vgmstream（BD2 仓库自带同一套二进制）。"""
    here = Path(__file__).resolve().parent
    return here / "vgmstream"


def _vgmstream(cli: Path, args: list[str]) -> str:
    """调用 vgmstream-cli（DLL 需与 exe 同目录；铁律见模块 docstring）。"""
    env = dict(os.environ)
    env["PATH"] = str(cli.parent) + os.pathsep + env.get("PATH", "")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(
        [str(cli), *args],
        capture_output=True, text=True, env=env, timeout=600,
        creationflags=creationflags, encoding="utf-8", errors="replace",
    )
    return r.stdout or r.stderr


def _find_fsb5(data: bytes) -> int:
    """定位内嵌 FSB5 起始偏移（本格式：顶层 SND 块里直接连着 FSB5）。"""
    return data.find(b"FSB5")


def _riff_chunks(data: bytes) -> list[dict]:
    """粗扫顶层 RIFF 子块（只认 4 个可打印字符的块 id，SND 之后跳过）。"""
    chunks: list[dict] = []
    pos = 0
    end = len(data)
    while pos + 8 <= end:
        cid = data[pos:pos + 4]
        if cid == b"RIFF":
            size = int.from_bytes(data[pos + 4:pos + 8], "little")
            chunks.append({"id": "RIFF", "offset": pos, "size": size,
                           "form": data[pos + 8:pos + 12].decode("ascii", "replace")})
            pos += 12
            continue
        if cid == b"LIST":
            size = int.from_bytes(data[pos + 4:pos + 8], "little")
            chunks.append({"id": "LIST", "offset": pos, "size": size,
                           "type": data[pos + 8:pos + 12].decode("ascii", "replace")})
            pos += 8 + size + (size & 1)
            continue
        if not all(0x20 <= b < 0x7F for b in cid):
            break  # SND 数据区开始，结束粗扫
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        chunks.append({"id": cid.decode("ascii", "replace"), "offset": pos, "size": size})
        pos += 8 + size + (size & 1)
    return chunks


def _fsb5_names_fallback(data: bytes, fsb5_off: int, max_hits: int = 512) -> list[str]:
    """FSB5 名字表解析失败时的回退：正则扫文件里的 cue 名（保持出现顺序去重）。"""
    names: list[str] = []
    seen: set[bytes] = set()
    for m in CUE_NAME_RE.finditer(data, fsb5_off):
        b = m.group(0)
        if b not in seen:
            seen.add(b)
            names.append(b.decode("ascii", "replace"))
            if len(names) >= max_hits:
                break
    # 情绪名顺序不稳定时按文件出现顺序即可；数量一般 == numSamples
    return names


def probe(bytes_path: str | os.PathLike,
          vgmstream_dir: str | os.PathLike | None = None) -> dict:
    """判定格式并列出内部条目，返回 JSON 兼容 dict。

    {format, entries, decoder, notes, detail}
    """
    data = Path(bytes_path).read_bytes()
    res: dict = {"format": None, "entries": 0, "decoder": None, "notes": [], "detail": {}}

    # 1) 常见魔数
    magics_found: list[dict] = []
    for magic, name in RIFF_MAGICS.items():
        i = data.find(magic)
        if i != -1:
            magics_found.append({"magic": magic.decode("ascii", "replace"), "offset": i, "desc": name})
    res["detail"]["magics"] = magics_found

    fsb5_off = _find_fsb5(data)
    decoder_ok = False
    if data.startswith(b"RIFF") and data[8:12] == b"FEV " and fsb5_off != -1:
        # 2) RIFF/FEV + 内嵌 FSB5
        res["format"] = "RIFF/FEV + embedded FSB5 (FMOD Designer baked voice bank)"
        chunks = _riff_chunks(data)
        res["detail"]["riff_chunks"] = chunks
        res["detail"]["fsb5_offset"] = fsb5_off
        res["detail"]["fsb5_size"] = len(data) - fsb5_off
        if fsb5_off + 0x28 <= len(data):
            ver = int.from_bytes(data[fsb5_off + 4:fsb5_off + 8], "little")
            num = int.from_bytes(data[fsb5_off + 8:fsb5_off + 12], "little")
            res["detail"]["fsb5_version"] = ver
            res["detail"]["fsb5_num_samples"] = num

        # 3) vgmstream 元数据：stream count / 名 / 编码 / 码率
        cli = None
        vdir = Path(vgmstream_dir) if vgmstream_dir else _default_vgmstream_dir()
        cand = vdir / "vgmstream-cli.exe"
        if cand.exists():
            cli = cand
        elif shutil.which("vgmstream-cli"):
            cli = Path(shutil.which("vgmstream-cli"))
        if cli is None:
            res["notes"].append("vgmstream-cli 未找到（默认 tools/vgmstream/），"
                                "entries 用回退正则扫描，无法解码")
        else:
            with tempfile.TemporaryDirectory() as td:
                fsb = Path(td) / "voice.fsb"
                fsb.write_bytes(data[fsb5_off:])
                out = _vgmstream(cli, ["-m", str(fsb)])
                m = re.search(r"stream count:\s*(\d+)", out)
                count = int(m.group(1)) if m else 0
                res["entries"] = count
                enc = re.search(r"encoding:\s*(.+)", out)
                rate = re.search(r"sample rate:\s*(\d+)", out)
                ch = re.search(r"channels:\s*(\d+)", out)
                meta_src = re.search(r"metadata from:\s*(.+)", out)
                names: list[str] = []
                durations: list[float] = []
                for i in range(1, count + 1):
                    o = _vgmstream(cli, ["-m", "-s", str(i), str(fsb)])
                    nm = re.search(r"stream name:\s*(.+)", o)
                    names.append(nm.group(1).strip() if nm else f"cue{i}")
                    d = re.search(r"play duration:.*?\(0:(\d+\.\d+) seconds\)", o, re.S)
                    durations.append(float(d.group(1)) if d else 0.0)
                res["detail"]["codec"] = enc.group(1).strip() if enc else None
                res["detail"]["sample_rate"] = int(rate.group(1)) if rate else None
                res["detail"]["channels"] = int(ch.group(1)) if ch else None
                res["detail"]["vgmstream_meta"] = meta_src.group(1).strip() if meta_src else None
                res["detail"]["stream_names"] = names
                res["detail"]["durations_s"] = durations
                if names:
                    res["detail"]["total_duration_s"] = round(sum(durations), 1)
                    res["detail"]["duration_min_max"] = [round(min(durations), 2), round(max(durations), 2)]
                res["decoder"] = f"vgmstream-cli（{enc.group(1).strip() if enc else '未知编码'}）"
                res["decoder_cmd"] = f"{cli} -o {{out.wav}} -s {{1-based stream index}} voice.fsb"
                decoder_ok = count > 0
                res["notes"].append("FSB5 切片自顶层 SND 块（vgmstream 的 .bank/.fev 原生支持只覆盖 "
                                    "BNKI/SNDH 变体，此包需手动切片成 .fsb 再解码，见 decode_voice）。")
        if not decoder_ok and not res["entries"]:
            names = _fsb5_names_fallback(data, fsb5_off)
            if names:
                res["entries"] = len(names)
                res["detail"]["stream_names"] = names
                res["notes"].append("entries 来自 FSB5 名字表正则回退（未走 vgmstream）。")
        if not res["decoder"]:
            res["decoder"] = "需 vgmstream-cli（见 tools/vgmstream/）"
    else:
        # 其它格式：给出证据与 TODO
        res["notes"].append("非 RIFF/FEV+FSB5 容器，本脚本仅支持互动语音包；common-sound 包未覆盖。")
        if magics_found:
            res["format"] = "未知容器（疑似 " + " / ".join(
                m["desc"] for m in magics_found[:3]) + "）"
        else:
            res["format"] = "未知/加密字节流"
        res["decoder"] = "TODO：待研究对应解码方案"

    return res


def decode_voice(bytes_path: str | os.PathLike,
                 out_dir: str | os.PathLike,
                 vgmstream_dir: str | os.PathLike | None = None) -> list[Path]:
    """把 BD2 互动语音包解码为 {cue}.wav，返回产物路径列表。

    流程：定位内嵌 FSB5 -> 切片成临时 .fsb（finally 删除）
          -> vgmstream 逐 stream 解码（-s N 1-based，cue 名做文件名）。
    失败/缺 vgmstream 时返回 []（判定信息走 probe()）。
    """
    data = Path(bytes_path).read_bytes()
    fsb5_off = _find_fsb5(data)
    if fsb5_off == -1:
        return []

    vdir = Path(vgmstream_dir) if vgmstream_dir else _default_vgmstream_dir()
    cli = vdir / "vgmstream-cli.exe"
    if not cli.exists():
        cli = Path(shutil.which("vgmstream-cli")) if shutil.which("vgmstream-cli") else Path("vgmstream-cli")
        if not shutil.which("vgmstream-cli"):
            return []

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    with tempfile.TemporaryDirectory() as td:
        fsb = Path(td) / "voice.fsb"  # vgmstream 按扩展名识别，必须 .fsb
        fsb.write_bytes(data[fsb5_off:])
        meta = _vgmstream(cli, ["-m", str(fsb)])
        m = re.search(r"stream count:\s*(\d+)", meta)
        count = int(m.group(1)) if m else 0
        for i in range(1, count + 1):
            o = _vgmstream(cli, ["-m", "-s", str(i), str(fsb)])
            nm = re.search(r"stream name:\s*(.+)", o)
            name = nm.group(1).strip() if nm else f"cue{i}"
            safe = re.sub(r'[\\/:*?"<>|]', "_", name)
            wav = out / f"{safe}.wav"
            if wav.exists() and wav.stat().st_size > 44:
                produced.append(wav)
                continue
            _vgmstream(cli, ["-o", str(wav), "-s", str(i), str(fsb)])
            if wav.exists() and wav.stat().st_size > 44:
                produced.append(wav)
    return produced


def main() -> int:
    # 仓库约定：stdout/stderr 强制 UTF-8（GBK 控制台/管道下输出确定可解析）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="BD2 互动语音包格式探测/解码")
    ap.add_argument("bytes_file", help="TextAsset 原始字节文件（如 Interaction_Char003892）")
    ap.add_argument("--decode", action="store_true", help="探测后执行解码")
    ap.add_argument("--out", default=None, help="解码输出目录（默认 ./voice_probe_out）")
    ap.add_argument("--vgmstream", default=None, help="vgmstream-cli 所在目录（默认 tools/vgmstream/）")
    args = ap.parse_args()

    res = probe(args.bytes_file, vgmstream_dir=args.vgmstream)
    print(json.dumps(res, ensure_ascii=False, indent=2))

    if args.decode:
        out_dir = args.out or os.path.join(os.getcwd(), "voice_probe_out")
        produced = decode_voice(args.bytes_file, out_dir, vgmstream_dir=args.vgmstream)
        print(f"\n[decode_voice] produced {len(produced)} wav(s) in {out_dir}")
        for p in produced:
            print("  " + str(p))
        if not produced:
            sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())