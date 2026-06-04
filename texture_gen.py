"""
texture_gen.py - Rich procedural texture generator for Gamebook Studio
Generates: scene illustrations, item icons, character silhouettes, backgrounds
Uses PIL/Pillow with deterministic seeding from scene/item names.
"""
import os
import hashlib
import math
import random
import json

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _seed_from(s):
    """Deterministic seed from string."""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


def _get_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _clamp(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


# ═══════════════════════════════════════════════════════════════
# SCENE ILLUSTRATION — landscape/environment with atmosphere
# ═══════════════════════════════════════════════════════════════
def generate_scene_illustration(width, height, title, tags, base_color, save_path):
    """Generate a scene illustration with terrain, sky, and atmosphere."""
    if not HAS_PIL:
        return None

    rng = random.Random(_seed_from(title))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Palette from tags
    is_dark = any(t in tags for t in ["underground", "dungeon", "horror", "boss", "dark"])
    is_forest = any(t in tags for t in ["forest", "outdoor"])
    is_combat = any(t in tags for t in ["combat", "boss", "climax"])
    is_space = any(t in tags for t in ["space"])
    is_indoor = any(t in tags for t in ["indoor", "shop", "investigation"])
    is_water = any(t in tags for t in ["innsmouth", "harbor"])

    # Sky gradient
    if is_dark or any(t in tags for t in ["underground"]):
        sky_top = (15, 10, 25)
        sky_bot = (35, 25, 45)
    elif is_space:
        sky_top = (5, 5, 20)
        sky_bot = (10, 15, 40)
    elif is_combat:
        sky_top = (60, 15, 10)
        sky_bot = (120, 40, 20)
    elif is_water:
        sky_top = (30, 50, 70)
        sky_bot = (50, 80, 90)
    else:
        sky_top = (base_color[0] // 3, base_color[1] // 3, base_color[2] // 2 + 30)
        sky_bot = (base_color[0] // 2, base_color[1] // 2, base_color[2] // 2)

    horizon = int(height * 0.55)
    for y in range(horizon):
        t = y / horizon
        c = _lerp_color(sky_top, sky_bot, t)
        draw.line([(0, y), (width, y)], fill=c)

    # Stars for dark/space scenes
    if is_dark or is_space:
        for _ in range(rng.randint(30, 80)):
            sx = rng.randint(0, width)
            sy = rng.randint(0, horizon - 20)
            brightness = rng.randint(140, 255)
            sz = rng.choice([1, 1, 1, 2])
            draw.ellipse([sx, sy, sx + sz, sy + sz],
                         fill=(brightness, brightness, brightness - rng.randint(0, 40)))

    # Moon/planet for dark scenes
    if is_dark or is_space:
        mx = rng.randint(width // 4, 3 * width // 4)
        my = rng.randint(20, horizon // 3)
        mr = rng.randint(15, 30)
        moon_c = (200, 190, 170) if not is_space else (rng.randint(100, 200), rng.randint(60, 150), rng.randint(100, 220))
        draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=moon_c)
        # Craters
        for _ in range(3):
            cx2 = mx + rng.randint(-mr // 2, mr // 2)
            cy2 = my + rng.randint(-mr // 2, mr // 2)
            cr = rng.randint(2, mr // 4)
            darker = tuple(max(0, c2 - 30) for c2 in moon_c)
            draw.ellipse([cx2 - cr, cy2 - cr, cx2 + cr, cy2 + cr], fill=darker)

    # Ground
    ground_top = (base_color[0] // 2, base_color[1] // 2, base_color[2] // 3)
    ground_bot = (max(0, base_color[0] // 3 - 10), max(0, base_color[1] // 3 - 10), max(0, base_color[2] // 4))
    if is_water:
        ground_top = (20, 40, 60)
        ground_bot = (10, 20, 40)
    for y in range(horizon, height):
        t = (y - horizon) / (height - horizon)
        c = _lerp_color(ground_top, ground_bot, t)
        draw.line([(0, y), (width, y)], fill=c)

    # Terrain features — mountains/hills
    if not is_indoor:
        n_peaks = rng.randint(3, 7)
        for i in range(n_peaks):
            px = rng.randint(-50, width + 50)
            pw = rng.randint(60, 180)
            ph = rng.randint(30, horizon // 2)
            peak_y = horizon - ph
            peak_c = _lerp_color(sky_bot, ground_top, 0.5)
            peak_c = tuple(_clamp(c2 + rng.randint(-20, 20)) for c2 in peak_c)
            points = [(px - pw, horizon), (px, peak_y), (px + pw, horizon)]
            draw.polygon(points, fill=peak_c)

    # Trees for forest
    if is_forest:
        for _ in range(rng.randint(8, 20)):
            tx = rng.randint(0, width)
            ty = rng.randint(horizon - 30, horizon + 40)
            th = rng.randint(30, 80)
            tw = rng.randint(15, 35)
            trunk_c = (50 + rng.randint(0, 30), 30 + rng.randint(0, 20), 15)
            leaf_c = (20 + rng.randint(0, 40), 60 + rng.randint(0, 60), 20 + rng.randint(0, 30))
            draw.rectangle([tx - 3, ty - th // 3, tx + 3, ty], fill=trunk_c)
            draw.polygon([(tx - tw, ty - th // 3),
                          (tx, ty - th),
                          (tx + tw, ty - th // 3)], fill=leaf_c)

    # Water waves
    if is_water:
        for wy in range(horizon + 20, height, 8):
            for wx in range(0, width, 3):
                wave = math.sin(wx * 0.05 + wy * 0.1 + rng.random()) * 3
                brightness = rng.randint(30, 60)
                if abs(wave) > 1.5:
                    draw.point((wx, wy + int(wave)),
                               fill=(brightness, brightness + 20, brightness + 40))

    # Indoor elements — walls, floor pattern
    if is_indoor:
        # Stone wall texture
        for y in range(0, horizon, 20):
            for x in range(0, width, 40):
                offset = 20 if (y // 20) % 2 else 0
                v = rng.randint(40, 70)
                draw.rectangle([x + offset, y, x + offset + 38, y + 18],
                               fill=(v, v - 5, v - 10),
                               outline=(v - 15, v - 20, v - 25))

    # Atmospheric fog/mist at horizon
    fog_img = Image.new("RGBA", (width, 60), (0, 0, 0, 0))
    fog_draw = ImageDraw.Draw(fog_img)
    fog_color = (*sky_bot, 80)
    for fy in range(60):
        alpha = int(80 * (1 - fy / 60))
        fog_draw.line([(0, fy), (width, fy)],
                      fill=(*sky_bot, alpha))
    img.paste(Image.alpha_composite(
        img.crop((0, horizon - 30, width, horizon + 30)),
        fog_img), (0, horizon - 30))

    # Vignette
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vg_draw = ImageDraw.Draw(vignette)
    for i in range(40):
        alpha = int(120 * (i / 40) ** 2)
        vg_draw.rectangle([i, i, width - i, height - i],
                          outline=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, vignette)

    # Title overlay
    font = _get_font(18)
    # Shadow
    draw2 = ImageDraw.Draw(img)
    bbox = draw2.textbbox((0, 0), title, font=font)
    tw = bbox[2] - bbox[0]
    tx = (width - tw) // 2
    ty = height - 35
    draw2.text((tx + 1, ty + 1), title, fill=(0, 0, 0, 200), font=font)
    draw2.text((tx, ty), title, fill=(230, 220, 200), font=font)

    img = img.convert("RGB")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)
    return img


# ═══════════════════════════════════════════════════════════════
# ITEM ICON — type-specific shapes with colored backgrounds
# ═══════════════════════════════════════════════════════════════
ITEM_TYPE_SHAPES = {
    "weapon":     "sword",
    "armor":      "shield",
    "quest":      "star",
    "consumable": "potion",
    "protection": "star",
    "tool":       "gear",
    "tech":       "gear",
    "cyberware":  "chip",
    "upgrade":    "gear",
    "evidence":   "scroll",
    "personal":   "gem",
    "misc":       "gem",
}

def generate_item_icon(size, item_name, item_type, base_color, save_path):
    """Generate a detailed item icon with type-specific shape."""
    if not HAS_PIL:
        return None

    rng = random.Random(_seed_from(item_name))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle with gradient
    c1 = tuple(_clamp(base_color[i] + rng.randint(-20, 40)) for i in range(3))
    c2 = tuple(max(0, c - 40) for c in c1)
    cx, cy = size // 2, size // 2
    r = size // 2 - 3
    for ri in range(r, 0, -1):
        t = ri / r
        c = _lerp_color(c2, c1, t)
        draw.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=(*c, 230))

    # Border
    draw.ellipse([2, 2, size - 3, size - 3], outline=(200, 200, 200, 180), width=2)

    shape = ITEM_TYPE_SHAPES.get(item_type, "gem")
    m = size // 2  # midpoint
    s = size // 4  # half-size of shape

    icon_c = (240, 230, 210)
    shadow_c = (40, 30, 20, 100)

    if shape == "sword":
        # Blade
        draw.polygon([(m, m - s - 4), (m - 3, m + s - 4), (m + 3, m + s - 4)],
                     fill=icon_c)
        # Guard
        draw.rectangle([m - s // 2, m + s - 6, m + s // 2, m + s - 2],
                       fill=(180, 160, 80))
        # Grip
        draw.rectangle([m - 2, m + s - 2, m + 2, m + s + 5],
                       fill=(120, 80, 40))

    elif shape == "shield":
        pts = [(m, m - s), (m + s, m - s // 3), (m + s - 2, m + s - 4),
               (m, m + s + 2), (m - s + 2, m + s - 4), (m - s, m - s // 3)]
        draw.polygon(pts, fill=(100, 120, 160), outline=icon_c, width=2)
        draw.line([(m, m - s + 4), (m, m + s - 2)], fill=icon_c, width=2)
        draw.line([(m - s + 6, m), (m + s - 6, m)], fill=icon_c, width=1)

    elif shape == "star":
        pts = []
        for i in range(10):
            angle = math.pi / 2 + i * math.pi / 5
            r2 = s + 2 if i % 2 == 0 else s // 2
            pts.append((m + int(r2 * math.cos(angle)),
                        m - int(r2 * math.sin(angle))))
        draw.polygon(pts, fill=(220, 200, 80), outline=(255, 240, 120))

    elif shape == "potion":
        # Bottle
        draw.rectangle([m - 3, m - s, m + 3, m - s // 2], fill=(180, 180, 180))  # neck
        draw.ellipse([m - s // 2 - 2, m - s // 2, m + s // 2 + 2, m + s + 2],
                     fill=(rng.randint(60, 200), rng.randint(80, 220), rng.randint(60, 200)),
                     outline=(200, 200, 200))
        # Highlight
        draw.arc([m - s // 4, m - s // 4, m, m + s // 3],
                 200, 340, fill=(255, 255, 255, 150), width=1)

    elif shape == "gear":
        for i in range(8):
            angle = i * math.pi / 4
            x1 = m + int((s - 2) * math.cos(angle))
            y1 = m + int((s - 2) * math.sin(angle))
            draw.rectangle([x1 - 3, y1 - 3, x1 + 3, y1 + 3], fill=icon_c)
        draw.ellipse([m - s // 2, m - s // 2, m + s // 2, m + s // 2],
                     fill=(100, 100, 110), outline=icon_c, width=2)
        draw.ellipse([m - 3, m - 3, m + 3, m + 3], fill=icon_c)

    elif shape == "chip":
        draw.rectangle([m - s + 2, m - s + 4, m + s - 2, m + s - 4],
                       fill=(30, 60, 30), outline=(100, 200, 100))
        for pin in range(4):
            px = m - s + 6 + pin * (s - 4) // 2
            draw.rectangle([px, m - s + 1, px + 3, m - s + 4], fill=(200, 200, 200))
            draw.rectangle([px, m + s - 4, px + 3, m + s - 1], fill=(200, 200, 200))
        draw.rectangle([m - 4, m - 4, m + 4, m + 4], fill=(80, 180, 80))

    elif shape == "scroll":
        draw.rectangle([m - s + 2, m - s // 2, m + s - 2, m + s // 2 + 4],
                       fill=(200, 185, 150), outline=(150, 130, 90))
        for ly in range(m - s // 2 + 4, m + s // 2, 4):
            draw.line([(m - s + 6, ly), (m + s - 6, ly)],
                      fill=(120, 100, 70), width=1)
        # Rolls
        draw.ellipse([m - s, m - s // 2 - 3, m - s + 6, m - s // 2 + 3],
                     fill=(180, 165, 130), outline=(150, 130, 90))
        draw.ellipse([m + s - 6, m - s // 2 - 3, m + s, m - s // 2 + 3],
                     fill=(180, 165, 130), outline=(150, 130, 90))

    else:  # gem
        pts = [(m, m - s), (m + s - 2, m - 2), (m + s // 2, m + s - 2),
               (m - s // 2, m + s - 2), (m - s + 2, m - 2)]
        gem_c = (rng.randint(100, 255), rng.randint(80, 220), rng.randint(120, 255))
        draw.polygon(pts, fill=gem_c, outline=(255, 255, 255, 200))
        # Facet highlight
        draw.line([(m, m - s + 2), (m + s // 3, m)], fill=(255, 255, 255, 120))

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)
    return img


# ═══════════════════════════════════════════════════════════════
# BACKGROUND — large atmospheric image for the player view
# ═══════════════════════════════════════════════════════════════
def generate_background(width, height, theme_name, base_color, save_path):
    """Generate a background with subtle parchment/tech texture."""
    if not HAS_PIL:
        return None

    rng = random.Random(_seed_from(theme_name))
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Gradient
    c1 = tuple(_clamp(base_color[i] // 3 + 15) for i in range(3))
    c2 = tuple(_clamp(base_color[i] // 4 + 5) for i in range(3))
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=_lerp_color(c1, c2, t))

    # Noise texture
    for _ in range(width * height // 20):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        v = rng.randint(-8, 8)
        px = img.getpixel((x, y))
        img.putpixel((x, y), tuple(_clamp(px[i] + v) for i in range(3)))

    # Subtle border/frame
    border_c = tuple(_clamp(c + 20) for c in c1)
    draw.rectangle([0, 0, width - 1, height - 1], outline=border_c, width=3)
    draw.rectangle([8, 8, width - 9, height - 9], outline=border_c, width=1)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)
    return img


# ═══════════════════════════════════════════════════════════════
# CHARACTER SILHOUETTE
# ═══════════════════════════════════════════════════════════════
def generate_character(width, height, char_name, base_color, save_path):
    """Generate a character silhouette placeholder."""
    if not HAS_PIL:
        return None

    rng = random.Random(_seed_from(char_name))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = width // 2
    body_c = tuple(_clamp(base_color[i] + rng.randint(20, 80)) for i in range(3))
    outline_c = tuple(_clamp(c + 40) for c in body_c)

    # Head
    head_r = width // 6
    head_y = height // 5
    draw.ellipse([cx - head_r, head_y - head_r, cx + head_r, head_y + head_r],
                 fill=body_c, outline=outline_c, width=2)

    # Eyes
    ey = head_y - 2
    draw.ellipse([cx - head_r // 2 - 3, ey - 3, cx - head_r // 2 + 3, ey + 3],
                 fill=(220, 220, 200))
    draw.ellipse([cx + head_r // 2 - 3, ey - 3, cx + head_r // 2 + 3, ey + 3],
                 fill=(220, 220, 200))

    # Body
    shoulder_w = width // 3
    body_top = head_y + head_r
    body_bot = int(height * 0.7)
    draw.polygon([(cx - shoulder_w, body_top + 10),
                  (cx + shoulder_w, body_top + 10),
                  (cx + shoulder_w - 10, body_bot),
                  (cx - shoulder_w + 10, body_bot)],
                 fill=body_c, outline=outline_c, width=2)

    # Arms
    draw.line([(cx - shoulder_w, body_top + 15),
               (cx - shoulder_w - 15, body_bot - 20)],
              fill=outline_c, width=4)
    draw.line([(cx + shoulder_w, body_top + 15),
               (cx + shoulder_w + 15, body_bot - 20)],
              fill=outline_c, width=4)

    # Legs
    leg_top = body_bot
    draw.line([(cx - 10, leg_top), (cx - 15, height - 10)],
              fill=outline_c, width=5)
    draw.line([(cx + 10, leg_top), (cx + 15, height - 10)],
              fill=outline_c, width=5)

    # Name label
    font = _get_font(12)
    bbox = draw.textbbox((0, 0), char_name, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, height - 20), char_name,
              fill=(220, 210, 190), font=font)

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    img.save(save_path)
    return img


# ═══════════════════════════════════════════════════════════════
# GENERATE ALL — master function
# ═══════════════════════════════════════════════════════════════
def generate_all_placeholders(gamebook, folder_path, config=None):
    """Generate all placeholder textures for a gamebook."""
    if not HAS_PIL:
        print("  Pillow not installed — skipping texture generation")
        return

    cfg_tex = config.get("textures", {}) if config else {}
    scene_w = cfg_tex.get("scene_width", 480)
    scene_h = cfg_tex.get("scene_height", 280)
    icon_sz = cfg_tex.get("icon_size", 48)
    bg_w = cfg_tex.get("background_width", 1280)
    bg_h = cfg_tex.get("background_height", 800)
    char_w = cfg_tex.get("character_width", 200)
    char_h = cfg_tex.get("character_height", 320)

    tex_dir = os.path.join(folder_path, "assets", "textures")
    icon_dir = os.path.join(tex_dir, "icons")
    char_dir = os.path.join(tex_dir, "characters")
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(icon_dir, exist_ok=True)
    os.makedirs(char_dir, exist_ok=True)

    base = tuple(gamebook.theme_color) if gamebook.theme_color else (80, 60, 40)

    # Background
    bg_path = os.path.join(tex_dir, "background.png")
    if not os.path.exists(bg_path):
        generate_background(bg_w, bg_h, gamebook.title, base, bg_path)
        print(f"  Background: background.png")

    # Scene illustrations
    for sid, scene in gamebook.scenes.items():
        path = os.path.join(tex_dir, f"{sid}.png")
        if not os.path.exists(path):
            tags = scene.tags if scene.tags else []
            generate_scene_illustration(scene_w, scene_h, scene.title, tags, base, path)
            print(f"  Scene: {sid}.png")

    # Item icons
    for iid, item in gamebook.items.items():
        path = os.path.join(icon_dir, f"{iid}.png")
        if not os.path.exists(path):
            generate_item_icon(icon_sz, item.name, item.item_type, base, path)
            print(f"  Icon: {iid}.png")

    # Character placeholders (from scene tags/names)
    characters = set()
    for scene in gamebook.scenes.values():
        if "ally" in (scene.tags or []) or "encounter" in (scene.tags or []):
            # Extract character name from title
            characters.add(scene.title.replace("The ", "").split(" — ")[0][:20])
    for char_name in sorted(characters):
        safe = char_name.lower().replace(" ", "_").replace("'", "")
        path = os.path.join(char_dir, f"{safe}.png")
        if not os.path.exists(path):
            generate_character(char_w, char_h, char_name, base, path)
            print(f"  Character: {safe}.png")


# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    from data_model import GameBook
    import sys

    # Load config
    config = {}
    config_path = "./config.json"
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)

    folder = sys.argv[1] if len(sys.argv) > 1 else "./library"

    for entry in sorted(os.listdir(folder)):
        book_path = os.path.join(folder, entry)
        if os.path.isdir(book_path) and os.path.exists(os.path.join(book_path, "project.json")):
            print(f"\nGenerating textures for: {entry}")
            gb = GameBook.load(book_path)
            generate_all_placeholders(gb, book_path, config)
    print("\nDone.")
