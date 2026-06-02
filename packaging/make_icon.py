"""
Creates a placeholder icon if none exists.
Supports converting .jpeg/.jpg to .png for AppImage.
Run: python3 packaging/make_icon.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

def find_icon():
    for name in ["icon.png", "icon.jpg", "icon.jpeg"]:
        p = ASSETS / name
        if p.exists():
            return p
    return None

src = find_icon()

if src and src.suffix in (".jpg", ".jpeg"):
    from PIL import Image
    img = Image.open(src).convert("RGBA").resize((256, 256))
    out = ASSETS / "icon.png"
    img.save(out)
    print(f"Converted {src.name} → icon.png")
elif src:
    print(f"Icon exists: {src}")
else:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (9, 9, 11, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([32, 32, 224, 224], fill=(96, 165, 250, 255))
    d.ellipse([90, 90, 166, 166], fill=(9, 9, 11, 255))
    out = ASSETS / "icon.png"
    img.save(out)
    print(f"Created placeholder icon: {out}")
