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

        # 针对包含多套骨架目录的包（如 cutscene 包含 cutscene_char004201 与 cutscene_char004201_1）：
        # 若两套骨架贴图同名，遍历无序写入会导致次要/过场骨架的贴图覆盖主骨架贴图，引发碎裂花屏。
        # 此处预先扫描骨架所在 container 目录，锁定目标骨架（优先匹配 out_dir 名，否则取 skel 最大的主骨架），
        # 排除其他同名次要骨架目录下的同名资产。此外按【被拒骨架干名】做对象级过滤，
        # 并清理输出目录里的历史残留文件（旧版提取留下的次要骨架会残留成
        # "多层骨架叠加渲染、几个动画重叠在一起"——2026-10 cutscene004091 实测）。
        rejected_containers: set[str] = set()
        rejected_stems: set[str] = set()
        skel_folders: dict[str, list[tuple[str, int]]] = {}
        for obj in env.objects:
            if getattr(obj, "type", None) and obj.type.name == "TextAsset":
                c = getattr(obj, "container", "") or ""
                try:
                    d = obj.read()
                except Exception:
                    continue
                if (getattr(d, "m_Name", "") or "").lower().endswith(".skel"):
                    folder = c.rsplit("/", 1)[0] if "/" in c else ""
                    raw_len = len(d.m_Script) if hasattr(d, "m_Script") else 0
                    skel_folders.setdefault(folder, []).append((d.m_Name, raw_len))

        all_skels = [(nm, ln) for lst in skel_folders.values() for nm, ln in lst]
        if len(all_skels) > 1:
            dst_stem = dst.name
            main = next((nm for nm, _ in all_skels if nm[: -len(".skel")] == dst_stem), None)
            if main is None:
                main = max(all_skels, key=lambda x: x[1])[0]
            for nm, _ln in all_skels:
                if nm == main:
                    continue
                stem = nm[: -len(".skel")]
                rejected_stems.add(stem)
                for folder in skel_folders:
                    members = {n for n, _ in skel_folders[folder]}
                    if nm in members:
                        rejected_containers.add(folder.lower() + "/")
            # 自愈：删除输出目录里被拒骨架的历史残留（stem.atlas / stem.skel / stem.png / stem_N.png…）
            for stem in rejected_stems:
                for pattern in (stem + ".*", stem + "_*"):
                    for f in dst.glob(pattern):
                        try:
                            f.unlink()
                        except OSError:
                            pass

        for obj in env.objects:
            if getattr(obj, "path_id", None) in seen:
                continue
            seen.add(getattr(obj, "path_id", None))
            tname = obj.type.name
            if tname not in ("TextAsset", "Texture2D"):
                continue

            container = (getattr(obj, "container", "") or "").lower()
            if rejected_containers and any(container.startswith(rej) for rej in rejected_containers):
                continue

            try:
                data = obj.read()
            except Exception:  # noqa: BLE001
                continue
            name = data.m_Name or f"obj_{obj.path_id}"
            if rejected_stems:
                low = name.lower()
                for stem in rejected_stems:
                    ls = stem.lower()
                    if low == ls or low.startswith(ls + "_") or low.startswith(ls + "."):
                        name = None
                        break
            if name is None:
                continue
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
