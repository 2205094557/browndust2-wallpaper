"""插件注册表：自动发现 plugins/ 下的来源/提取/导出插件。"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path


class Plugin:
    kind = "base"
    id = "base"
    name = "基础插件"

    def __str__(self) -> str:
        return f"{self.kind}:{self.id} ({self.name})"


class SourcePlugin(Plugin):
    kind = "sources"

    def list_bundles(self):
        raise NotImplementedError

    def download(self, bundle, out_dir):
        raise NotImplementedError


class ExtractorPlugin(Plugin):
    kind = "extractors"

    def extract(self, bundle_path: str, out_dir: str) -> dict:
        raise NotImplementedError


class ExporterPlugin(Plugin):
    kind = "exporters"

    def export(self, skin, options, out_dir) -> str:
        raise NotImplementedError


class Registry:
    def __init__(self, plugins_root: Path) -> None:
        self.plugins_root = Path(plugins_root)
        self._plugins = {"sources": {}, "extractors": {}, "exporters": {}}

    def discover(self) -> "Registry":
        for kind in self._plugins:
            kind_dir = self.plugins_root / kind
            if not kind_dir.is_dir():
                continue
            for item in sorted(kind_dir.iterdir()):
                if item.name.startswith("_"):
                    continue
                if item.is_dir():
                    mod_name = f"plugins.{kind}.{item.name}"
                elif item.is_file() and item.suffix == ".py":
                    mod_name = f"plugins.{kind}.{item.stem}"
                else:
                    continue
                try:
                    mod = importlib.import_module(mod_name)
                except Exception as e:  # noqa: BLE001
                    print(f"[registry] 加载 {mod_name} 失败: {e}")
                    continue
                for _, cls in inspect.getmembers(mod, inspect.isclass):
                    if not issubclass(cls, Plugin) or cls is Plugin:
                        continue
                    if cls.kind != kind:
                        continue
                    pid = getattr(cls, "id", None)
                    if not pid or pid == "base":
                        continue
                    self._plugins[kind][pid] = cls()
        return self

    def get(self, kind: str, pid: str):
        return self._plugins.get(kind, {}).get(pid)

    def all(self, kind: str) -> list:
        return list(self._plugins.get(kind, {}).values())

    def summary(self) -> dict:
        return {k: [p.id for p in v.values()] for k, v in self._plugins.items()}