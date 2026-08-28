"""BD2 静态立绘提取插件：从 UI 贴图包直接导出 Texture2D。

BD2 的静态立绘（Illust_1/illust_charXXXXXX_NNN.png 等）是 bundle 里的
普通 Texture2D，无需图层合成——按名字精确匹配导出为 painting.png。
"""

from __future__ import annotations

from pathlib import Path

import UnityPy

from core.registry import ExtractorPlugin

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.22f1"


class StaticExtractor(ExtractorPlugin):
    id = "static"
    name = "静态立绘提取器"

    def extract(self, bundle_path: str, tex_name: str, out_dir: str) -> dict:
        """从 bundle 提取名为 tex_name 的 Texture2D，存为 painting.png。

        tex_name 不带 .png 后缀（如 illust_char003892_190）。
        """
        src = Path(bundle_path)
        dst = Path(out_dir)
        dst.mkdir(parents=True, exist_ok=True)
        target = tex_name.lower()
        env = UnityPy.load(str(src))
        best = None
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            try:
                data = obj.read()
            except Exception:  # noqa: BLE001
                continue
            name = (data.m_Name or "").lower()
            if name == target:
                best = data
                break
            # 兜底：同名多分辨率时取尺寸最大的
            if name.startswith(target) and name != target:
                try:
                    if best is None or data.m_Width * data.m_Height > best.m_Width * best.m_Height:
                        best = data
                except Exception:  # noqa: BLE001
                    pass
        if best is None:
            raise FileNotFoundError(f"bundle 中未找到贴图: {tex_name}")
        img = best.image
        out = dst / "painting.png"
        img.save(out)
        return {"image": "painting.png", "size": [img.width, img.height]}
