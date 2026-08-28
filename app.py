"""应用装配：注册插件、加载元数据、初始化资源库。"""

from __future__ import annotations

from pathlib import Path

from core.events import bus
from core.library import Library
from core.metadata import Metadata
from core.registry import Registry

ROOT = Path(__file__).resolve().parent


def build_app() -> dict:
    registry = Registry(ROOT / "plugins").discover()
    metadata = Metadata(ROOT / "resources" / "metadata")
    library = Library(ROOT / "resources" / "library.db")
    library.import_metadata(metadata.ships(), metadata.skins(), metadata.local_skins())
    return {"registry": registry, "metadata": metadata, "library": library, "bus": bus}


if __name__ == "__main__":
    app = build_app()
    print("插件注册表:", app["registry"].summary())
    print("舰船总数:", len(app["metadata"].ships()))
    print("皮肤总数:", len(app["metadata"].skins()))
    print("已下载皮肤:")
    for s in app["library"].downloaded_skins():
        print(f"  {s['ship']} · {s['name']} ({s['type']})")
    app["library"].close()