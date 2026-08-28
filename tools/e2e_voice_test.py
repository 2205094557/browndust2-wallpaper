# -*- coding: utf-8 -*-
"""验证 BD2 互动语音链路：解码 + voice_status。"""
import sys

sys.path.insert(0, r"D:\codex\browndust2-wallpaper")

import backend_server as bs  # noqa: E402

vs = bs.voice_status("char003892")
print("ok:", vs.get("ok"), "| has:", vs.get("has"), "| cues:", len(vs.get("cues", [])))
print("pick:", vs.get("pick"))
wavs = bs.ROOT / "resources" / "voice" / "char003892"
if wavs.is_dir():
    files = list(wavs.glob("*.wav"))
    print("wav files:", len(files))
    if files:
        print("sample:", files[0].name, files[0].stat().st_size, "bytes")
