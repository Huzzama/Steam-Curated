"""
Generate visually rich sale event banner images locally using Pillow.
No network requests — images are generated once and cached.
"""
import random
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from config import ASSETS_DIR

SALE_BANNERS_DIR = ASSETS_DIR / "sale_banners"
SALE_BANNERS_DIR.mkdir(parents=True, exist_ok=True)

BANNER_W = 560
BANNER_H = 70


def get_banner_path(event_key: str, color_top: str, color_bot: str, emoji: str) -> str:
    """Return local path to a banner image. Generated once, cached forever."""
    cache_path = SALE_BANNERS_DIR / f"{event_key}.png"
    if not cache_path.exists():
        _generate_banner(cache_path, color_top, color_bot, emoji)
    return str(cache_path)


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _generate_banner(path: Path, color_top: str, color_bot: str, emoji: str):
    W, H = BANNER_W, BANNER_H
    img  = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    c1 = _hex_to_rgb(color_top)
    c2 = _hex_to_rgb(color_bot)

    # Diagonal gradient (top-left to bottom-right)
    for y in range(H):
        for x in range(0, W, 2):
            t = (x / W * 0.4 + y / H * 0.6)
            t = min(1.0, max(0.0, t))
            color = _lerp_color(c1, c2, t)
            draw.line([(x, y), (x+1, y)], fill=color)

    # Subtle noise overlay for texture
    rng = random.Random(hash(emoji))
    noise = Image.new("RGB", (W, H))
    nd = ImageDraw.Draw(noise)
    for _ in range(W * H // 8):
        nx = rng.randint(0, W-1)
        ny = rng.randint(0, H-1)
        v  = rng.randint(180, 255)
        nd.point((nx, ny), fill=(v, v, v))
    noise = noise.filter(ImageFilter.GaussianBlur(radius=1))
    img   = Image.blend(img, noise, alpha=0.04)

    # Glowing circle accent (top-right area)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    cx, cy = int(W * 0.82), int(H * 0.3)
    for r in range(90, 0, -3):
        alpha = int(18 * (1 - r/90))
        bright = _lerp_color(c1, (255, 255, 255), 0.5)
        gd.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*bright, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    # Second subtle accent — bottom left
    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2   = ImageDraw.Draw(glow2)
    for r in range(60, 0, -4):
        alpha = int(10 * (1 - r/60))
        gd2.ellipse([(-r//2), (H-r//2), r//2, H+r//2], fill=(*c1, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), glow2).convert("RGB")

    # Horizontal shimmer line
    shimmer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shimmer)
    for x in range(W):
        alpha = int(30 * math.sin(math.pi * x / W))
        sd.line([(x, H//3 - 1), (x, H//3 + 1)], fill=(255, 255, 255, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), shimmer).convert("RGB")

    img.save(path, "PNG")