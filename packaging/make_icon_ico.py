"""
packaging/make_icon_ico.py
Converts assets/icon.jpeg / .jpg / .png to assets/icon.ico for Windows builds.
Run: python packaging/make_icon_ico.py
"""
from pathlib import Path
from PIL import Image

assets = Path("assets")
for ext in ["jpeg", "jpg", "png"]:
    src = assets / f"icon.{ext}"
    if src.exists():
        img = Image.open(src).convert("RGBA")
        img.save(
            assets / "icon.ico",
            sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
        )
        print(f"Converted {src} -> icon.ico")
        break
else:
    print("No icon source found in assets/ — skipping conversion")
