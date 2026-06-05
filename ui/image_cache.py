"""
Global LRU image cache — PySide6 version.
Returns QPixmap objects instead of CTkImage.
- O(1) set-based key lookup
- Pre-computed placeholder per size
- BILINEAR resize (2-3x faster than LANCZOS for thumbnails)
- Max 300 entries
"""
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, QSize
from PIL import Image

_CACHE: OrderedDict[str, QPixmap] = OrderedDict()
_MAX_SIZE   = 300
_KEY_SET: set[str] = set()
_placeholder_cache: dict[tuple, QPixmap] = {}


def get(path: Optional[str], size: tuple = (144, 200)) -> QPixmap:
    key = f"{path}|{size[0]}x{size[1]}"
    if key in _KEY_SET:
        _CACHE.move_to_end(key)
        return _CACHE[key]

    px = _load(path, size)
    _CACHE[key] = px
    _KEY_SET.add(key)
    _CACHE.move_to_end(key)

    while len(_CACHE) > _MAX_SIZE:
        k, _ = next(iter(_CACHE.items()))
        del _CACHE[k]
        _KEY_SET.discard(k)

    return px


def invalidate(app_id: str):
    keys = {k for k in _KEY_SET
            if f"/{app_id}.jpg|" in k or f"\\{app_id}.jpg|" in k}
    for k in keys:
        _CACHE.pop(k, None)
    _KEY_SET -= keys


def clear():
    _CACHE.clear()
    _KEY_SET.clear()
    _placeholder_cache.clear()


def _load(path: Optional[str], size: tuple) -> QPixmap:
    try:
        if path and Path(path).exists():
            img = Image.open(path)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.thumbnail(size, Image.BILINEAR)
            if img.size != size:
                canvas = Image.new("RGB", size, (20, 20, 24))
                x = (size[0] - img.size[0]) // 2
                y = (size[1] - img.size[1]) // 2
                canvas.paste(img.convert("RGB"), (x, y))
                img = canvas
            # PIL → QPixmap via bytes
            data   = img.tobytes("raw", "RGB")
            from PySide6.QtGui import QImage
            qimg   = QImage(data, size[0], size[1], QImage.Format.Format_RGB888)
            return QPixmap.fromImage(qimg)
    except Exception:
        pass
    return _placeholder(size)


def _placeholder(size: tuple) -> QPixmap:
    if size not in _placeholder_cache:
        px = QPixmap(size[0], size[1])
        px.fill(QColor(20, 20, 24))
        p = QPainter(px)
        p.setPen(QColor(39, 39, 42))
        p.drawRect(0, 0, size[0]-1, size[1]-1)
        p.setPen(QColor(96, 165, 250))
        p.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Space Mono", 16))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        p.end()
        _placeholder_cache[size] = px
    return _placeholder_cache[size]