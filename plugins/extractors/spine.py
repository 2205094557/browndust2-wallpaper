"""BD2 Spine 提取插件：从 bundle 提取 .skel/.atlas/贴图（Spine 4.1）。

与碧蓝版的关键差异：
- BD2 的主立绘/约会/尊爵 spine 资源存放在**全角色共享大包**里
  （illustspine 86MB / datingillust 434MB / illustspecial 438MB），
  提取时按关键词（角色 id / illust_datingN / specialillustN）过滤对象；
- 演出 cutscene 是每角色独立小包（isolated-cutsceneXXXXXX-group），全量提取；
- 新版 bundle 的 Unity 版本头被抹成 "0.0.0"，必须设 FALLBACK_UNITY_VERSION。
"""

from __future__ import annotations

from pathlib import Path

import UnityPy

from core.registry import ExtractorPlugin

# BD2 国际服实测运行时 Unity 2022.3.22f1（ReDustX 同款）；新版包版本头是占位符
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.22f1"


class SpineExtractor(ExtractorPlugin):
    id = "spine"
    name = "Spine 提取器"

    def extract(self, bundle_path: str, out_dir: str, keywords=None) -> dict:
        """提取 bundle 内的 TextAsset(.skel/.atlas/.bytes) 与 Texture2D。

        keywords: 可迭代的过滤关键词（大小写不敏感，子串匹配对象名）。
        None/空 = 不过滤（用于独立小包，如 cutscene）。
        """
        src = Path(bundle_path)
        dst = Path(out_dir)
        dst.mkdir(parents=True, exist_ok=True)
        keys = [k.lower() for k in (keywords or []) if k]

        env = UnityPy.load(str(src))
        result = {"skel": [], "atlas": [], "textures": [], "voice": []}
        seen: set[int] = set()
        for obj in env.objects:
            if getattr(obj, "path_id", None) in seen:
                continue
            seen.add(getattr(obj, "path_id", None))
            tname = obj.type.name
            if tname not in ("TextAsset", "Texture2D"):
                continue
            try:
                data = obj.read()
            except Exception:  # noqa: BLE001
                continue
            name = data.m_Name or f"obj_{obj.path_id}"
            if keys and not any(k in name.lower() for k in keys):
                continue
            try:
                if tname == "TextAsset":
                    script = data.m_Script
                    if isinstance(script, str):
                        script = script.encode("utf-8", "surrogateescape")
                    (dst / name).write_bytes(script)
                    low = name.lower()
                    if low.endswith(".skel"):
                        result["skel"].append(name)
                    elif low.endswith(".atlas"):
                        result["atlas"].append(name)
                    else:
                        result["voice"].append(name)
                else:
                    img = data.image
                    if img is None:
                        continue
                    img.save(dst / f"{name}.png")
                    result["textures"].append(f"{name}.png")
            except Exception:  # noqa: BLE001
                continue
        return result
