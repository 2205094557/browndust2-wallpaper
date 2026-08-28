"""简单事件总线：下载/提取进度等事件推送给监听者。"""

from __future__ import annotations

from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, name: str, handler: Callable) -> None:
        self._handlers.setdefault(name, []).append(handler)

    def off(self, name: str, handler: Callable) -> None:
        if name in self._handlers:
            try:
                self._handlers[name].remove(handler)
            except ValueError:
                pass

    def emit(self, name: str, **data) -> None:
        for h in self._handlers.get(name, []):
            try:
                h(**data)
            except Exception:  # noqa: BLE001
                pass


bus = EventBus()