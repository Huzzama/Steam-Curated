"""
Global LRU image cache for CTkImage objects.
Prevents reloading covers from disk on every render.
"""
from collections import OrderedDict
from pathlib import Path
from typing import Optional
import customtkinter as ctk
from PIL import Image, ImageDraw

_CACHE: OrderedDict[str, ctk.CTkImage] = OrderedDict()
_MAX_SIZE = 200  # max cached images


def get(path: Optional[str], size: tuple = (144, 200)) -> ctk.CTkImage:
    """
    Return a CTkImage from cache, loading from disk if needed.
    Key includes size so same image at different sizes coexists.
    """
    key = f"{path}|{size[0]}x{size[1]}"

    if key in _CACHE:
        _CACHE.move_to_end(key)   # LRU: mark as recently used
        return _CACHE[key]

    img = _load(path, size)
    _CACHE[key] = img
    _CACHE.move_to_end(key)

    # Evict oldest if over limit
    while len(_CACHE) > _MAX_SIZE:
        _CACHE.popitem(last=False)

    return img


def invalidate(app_id: str):
    """Remove all cached sizes for a given app_id."""
    keys = [k for k in _CACHE if f"/{app_id}.jpg|" in k or f"\\{app_id}.jpg|" in k]
    for k in keys:
        del _CACHE[k]


def clear():
    _CACHE.clear()


def _load(path: Optional[str], size: tuple) -> ctk.CTkImage:
    try:
        if path and Path(path).exists():
            img = Image.open(path).convert("RGB")
            img = img.resize(size, Image.LANCZOS)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        pass
    return _placeholder(size)


def _placeholder(size: tuple) -> ctk.CTkImage:
    img  = Image.new("RGB", size, color=(20, 20, 24))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0]-1, size[1]-1], outline=(39, 39, 42), width=1)
    draw.text((size[0]//2, size[1]//2), "?", fill=(96, 165, 250), anchor="mm")
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)
