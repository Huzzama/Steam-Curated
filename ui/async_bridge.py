"""
Run work off the GUI thread and get the result back ON the GUI thread.

    run_async(self, lambda: fetch(), on_done=self._apply)          # result or Exception
    run_async(self, work, on_done=..., on_progress=self._step)     # work(progress) gets a callable

Why: QTimer.singleShot(0, fn) called from a plain threading.Thread never
fires (the thread has no Qt event loop) — that pattern had silently broken
the wishlist sync, cover download, price refresh and detail-panel refresh
buttons. Signals are the only safe way back.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal


class _Bridge(QObject):
    done     = Signal(object)
    progress = Signal(object)


def run_async(owner: QObject, work: Callable, on_done: Optional[Callable] = None,
              on_progress: Optional[Callable] = None) -> _Bridge:
    """
    work()            → runs in a daemon thread. If on_progress is given,
                        work(progress) is called with a thread-safe callable.
    on_done(result)   → GUI thread; result is the return value or the Exception.
    on_progress(x)    → GUI thread.
    The bridge is parented to *owner* so callbacks stop if the owner dies.
    """
    bridge = _Bridge(owner)
    if on_done:
        bridge.done.connect(on_done)
    if on_progress:
        bridge.progress.connect(on_progress)

    def _run():
        try:
            if on_progress:
                res = work(bridge.progress.emit)
            else:
                res = work()
        except Exception as e:      # noqa: BLE001 — delivered to the caller
            res = e
        bridge.done.emit(res)
        bridge.deleteLater()

    threading.Thread(target=_run, daemon=True).start()
    return bridge
