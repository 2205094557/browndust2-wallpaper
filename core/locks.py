# -*- coding: utf-8 -*-
"""跨模块实例共享的进程内锁。

PyInstaller 打包后，同一份代码可能被从 PYZ 和磁盘分别导入，形成多个模块实例，
模块级 threading.Lock 会因此“各自为政”导致并发失效；Windows 命名互斥体在
frozen 环境又有句柄/释放语义的坑。这里把锁挂在 sys 的全局字典上——
sys 对象在进程内必然唯一，无论模块被加载多少次，同名锁都返回同一把
threading.Lock，可靠且无 OS 层副作用。

用途：后端 run_tool 与 static 提取器都改写全局 sys.argv，并发下载时必须串行化。
"""

from __future__ import annotations

import sys
import threading


def _locks() -> dict[str, threading.Lock]:
    if not hasattr(sys, "_bd2_locks"):
        sys._bd2_locks = {}  # type: ignore[attr-defined]
    return sys._bd2_locks  # type: ignore[attr-defined]


def named_lock(name: str) -> threading.Lock:
    locks = _locks()
    lock = locks.get(name)
    if lock is None:
        lock = threading.Lock()
        locks[name] = lock
    return lock
