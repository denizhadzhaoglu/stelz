"""Render week-1 IG launch visuals that don't require Figma/AE.

Outputs to projects/spot-the-brand/assets/ig-week1/:
  - thu-static-quote.png (1080x1350, IG portrait, quote card)
  - mon-reel-cover.png  (1080x1920, IG reel 9:16, hero overlay)
  - fri-reel-cover.png  (1080x1920, IG reel 9:16, compilation overlay)

These are baseline visuals. Lukas can polish in Figma/AE if needed,
but they're publishable as-is.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import os

OUT = Path(__file__).resolve().parent.parent / "projects" / "spot-the-brand" / "assets" / "ig-week1"
OUT.mkdir(parents=True, exist_ok=True)

ACCENT = (255, 19, 0)
BLACK = (10, 10, 10)
WHITE = (237, 237, 237)
MUTED = (136, 136, 136)
GOLD = (251, 191, 36)

def font(size, bold=False):
    """Try system fonts; fall back to default if not installed."""
    candidates_bold = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in (candidates_bold if bold else candidates_regular):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def font_mono(size):
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_wordmark(draw, x, y, size=28, color=WHITE):
    """Spot the Brand wordmark with red period."""
    f = font(size, bold=True)
    txt1 = "Spot the Brand"
    txt2 = "."
    draw.text((x, y), txt1, fill=color, font=f)
    # Position the period right after; PIL doesn't give easy text-width on default,
    # so we just approximate by glyph count.
    bbox = draw.textbbox((x, y), txt1, font=f)
    end_x = bbox[2]
    draw.text((end_x, y), txt2, fill=ACCENT, font=f)


def draw_dashed_rect(draw, x, y, w, h, color, stroke=4, dash=24, gap=14):
    """Draw a dashed rectangle outline."""
    # top
    cur = x
    while cur < x + w:
        nx = min(cur + dash, x + w)
        draw.line([(cur, y), (nx, y)], fill=color, width=stroke)
        cur = nx + gap
    # bottom
    cur = x
    while cur < x + w:
        nx = min(cur + dash, x + w)
        draw.line([(cur, y + h), (nx, y + h)], fill=color, width=stroke)
        cur = nx + gap
    # left
    cur = y
    while cur < y + h:
        ny = min(cur + dash, y + h)
        draw.line([(x, cur), (x, ny)], fill=color, width=stroke)
        cur = ny + gap
    # right
    cur = y
    while cur < y + h:
        ny = min(cur + dash, y + h)
        draw.line([(x + w, cur), (x + w, ny)], fill=color, width=stroke)
        cur = ny + gap


def render_thu_quote():
    """Thursday static quote card: 1080×1350 (IG portrait)"""
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)

    # faint crosshair (background motif)
    draw.line([(0, H // 2), (W, H // 2)], fill=(60, 30, 30), width=1)
    draw.line([(W // 2, 0), (W // 2, H)], fill=(60, 30, 30), width=1)

    # detected label top
    mono_sm = font_mono(20)
    draw.text((60, 80), "DETECTED · 1.00", fill=ACCENT, font=mono_sm)

    # main quote — large display
    f_big = font(90, bold=True)
    quote_lines = [
        "We see what",
        "your social",
        "tool misses.",
    ]
    y = 320
    for line in quote_lines:
        draw.text((60, y), line, fill=WHITE, font=f_big)
        y += 110

    # subhead
    f_sub = font(32)
    draw.text((60, 750), "Visual brand monitoring.", fill=MUTED, font=f_sub)
    draw.text((60, 800), "Built for the way people post in 2026.", fill=MUTED, font=f_sub)

    # wordmark bottom
    draw_wordmark(draw, 60, H - 100, size=26, color=WHITE)

    # tiny URL bottom-right
    f_mini = font_mono(16)
    url = "spotyourbrand.com"
    bbox = draw.textbbox((0, 0), url, font=f_mini)
    draw.text((W - 60 - (bbox[2] - bbox[0]), H - 90), url, fill=MUTED, font=f_mini)

    out = OUT / "thu-static-quote.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out}")


def render_mon_reel_cover():
    """Monday reel cover: 1080×1920 (IG reel)"""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)

    # red radial-ish glow background (approx with concentric circles)
    for r in range(1200, 0, -40):
        alpha = int(40 * (1 - r / 1200))
        if alpha <= 0: continue
        # blend manually
        layer = Image.new("RGB", (W, H), (alpha, 0, 0))
        img = Image.blend(img, layer, 0.05)
    draw = ImageDraw.Draw(img)

    # crosshair
    draw.line([(0, H // 2), (W, H // 2)], fill=(60, 20, 20), width=2)
    draw.line([(W // 2, 0), (W // 2, H)], fill=(60, 20, 20), width=2)

    # bounding box around center "product placeholder"
    bx, by, bw, bh = 290, 700, 500, 500
    draw_dashed_rect(draw, bx, by, bw, bh, ACCENT, stroke=5, dash=30, gap=18)

    # detected label
    mono = font_mono(28)
    draw.text((bx, by - 50), "DETECTED · 0.94", fill=ACCENT, font=mono)

    # center placeholder text
    f_mini = font_mono(20)
    draw.text((W // 2 - 100, H // 2), "[ brand product ]", fill=(200, 100, 100), font=f_mini)

    # headline below
    f_head = font(72, bold=True)
    lines = [
        "Your brand is in",
        "more posts than",
        "you think.",
    ]
    y = 1370
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=f_head)
        x = (W - (bbox[2] - bbox[0])) // 2
        col = ACCENT if "you think" in line else WHITE
        draw.text((x, y), line, fill=col, font=f_head)
        y += 90

    # wordmark + URL
    f_word = font(32, bold=True)
    f_url = font_mono(18)
    bbox = draw.textbbox((0, 0), "Spot the Brand", font=f_word)
    wm_x = (W - (bbox[2] - bbox[0]) - 20) // 2
    draw.text((wm_x, H - 130), "Spot the Brand", fill=WHITE, font=f_word)
    draw.text((wm_x + (bbox[2] - bbox[0]) + 2, H - 130), ".", fill=ACCENT, font=f_word)

    url = "SPOTYOURBRAND.COM"
    bbox = draw.textbbox((0, 0), url, font=f_url)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, H - 80), url, fill=MUTED, font=f_url)

    out = OUT / "mon-reel-cover.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out}")


def render_fri_reel_cover():
    """Friday compilation reel cover: 1080×1920"""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)

    # 4 stacked mini bounding boxes (compilation feel)
    box_w, box_h = 700, 300
    for i, y_pos in enumerate([180, 540, 900, 1260]):
        x = (W - box_w) // 2
        draw_dashed_rect(draw, x, y_pos, box_w, box_h, ACCENT, stroke=4, dash=24, gap=14)
        mono = font_mono(22)
        draw.text((x, y_pos - 36), f"DETECTED · 0.{[94, 87, 91, 89][i]}", fill=ACCENT, font=mono)
        f_mini = font_mono(20)
        center_txt = "[ brand " + str(i + 1) + " ]"
        bbox = draw.textbbox((0, 0), center_txt, font=f_mini)
        draw.text((x + (box_w - (bbox[2] - bbox[0])) // 2,
                   y_pos + (box_h - 20) // 2), center_txt, fill=(150, 80, 80), font=f_mini)

    # Header top
    f_head = font(54, bold=True)
    header = "Four brands. Zero hashtags."
    bbox = draw.textbbox((0, 0), header, font=f_head)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, 80), header, fill=WHITE, font=f_head)

    # Footer wordmark
    f_word = font(32, bold=True)
    bbox = draw.textbbox((0, 0), "Spot the Brand", font=f_word)
    wm_x = (W - (bbox[2] - bbox[0]) - 20) // 2
    draw.text((wm_x, H - 130), "Spot the Brand", fill=WHITE, font=f_word)
    draw.text((wm_x + (bbox[2] - bbox[0]) + 2, H - 130), ".", fill=ACCENT, font=f_word)

    f_url = font_mono(18)
    url = "SPOTYOURBRAND.COM"
    bbox = draw.textbbox((0, 0), url, font=f_url)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, H - 80), url, fill=MUTED, font=f_url)

    out = OUT / "fri-reel-cover.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    render_thu_quote()
    render_mon_reel_cover()
    render_fri_reel_cover()
    print("\nAll week-1 visuals rendered to:", OUT)
