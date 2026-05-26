"""Render organic IG posts for @spotyourbrand launch week.

Builds publishable static assets:
  - 6-slide Tuesday carousel ("The Blind Spot")             1080x1350
  - 5-frame Wednesday story sequence ("Quick poll")         1080x1920
  - 4 grid-filler standalone posts                          1080x1350
  - 2 quote/manifesto posts                                 1080x1350

All assets land in projects/spot-the-brand/assets/ig-week1/organic/.
Posts can be uploaded as-is. Later they can be boosted via Meta Ads.

Brand discipline:
  - Spot Red #FF1300, Tier-1 Gold #FBBF24, Black #0A0A0A, Text #EDEDED
  - No customer names referenced (STELZ is pilot, not customer)
  - Categorical framing where customer evidence would be needed
  - Wordmark = "Spot the Brand" + red period
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import os

OUT = Path(__file__).resolve().parent.parent / "projects" / "spot-the-brand" / "assets" / "ig-week1" / "organic"
OUT.mkdir(parents=True, exist_ok=True)

ACCENT = (255, 19, 0)
BLACK = (10, 10, 10)
WHITE = (237, 237, 237)
MUTED = (136, 136, 136)
GOLD = (251, 191, 36)
DIM_RED = (60, 20, 20)
SOFT_GRAY = (30, 30, 30)


def font(size, bold=False):
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


def text_width(draw, text, f):
    bbox = draw.textbbox((0, 0), text, font=f)
    return bbox[2] - bbox[0]


def draw_wordmark(draw, x, y, size=28, color=WHITE):
    f = font(size, bold=True)
    txt1 = "Spot the Brand"
    draw.text((x, y), txt1, fill=color, font=f)
    end_x = x + text_width(draw, txt1, f)
    draw.text((end_x, y), ".", fill=ACCENT, font=f)


def wordmark_centered(draw, y, W, size=28, color=WHITE):
    f = font(size, bold=True)
    txt1 = "Spot the Brand"
    w = text_width(draw, txt1, f)
    x = (W - w - 14) // 2
    draw.text((x, y), txt1, fill=color, font=f)
    draw.text((x + w + 2, y), ".", fill=ACCENT, font=f)


def draw_dashed_rect(draw, x, y, w, h, color, stroke=4, dash=24, gap=14):
    cur = x
    while cur < x + w:
        nx = min(cur + dash, x + w)
        draw.line([(cur, y), (nx, y)], fill=color, width=stroke)
        cur = nx + gap
    cur = x
    while cur < x + w:
        nx = min(cur + dash, x + w)
        draw.line([(cur, y + h), (nx, y + h)], fill=color, width=stroke)
        cur = nx + gap
    cur = y
    while cur < y + h:
        ny = min(cur + dash, y + h)
        draw.line([(x, cur), (x, ny)], fill=color, width=stroke)
        cur = ny + gap
    cur = y
    while cur < y + h:
        ny = min(cur + dash, y + h)
        draw.line([(x + w, cur), (x + w, ny)], fill=color, width=stroke)
        cur = ny + gap


def draw_wrapped(draw, x, y, max_w, lines_text, f, fill, line_h):
    """Draw pre-split lines (one per element)."""
    for line in lines_text:
        draw.text((x, y), line, fill=fill, font=f)
        y += line_h
    return y


def page_number(draw, idx, total, W, H):
    f = font_mono(18)
    txt = f"{idx:02d} / {total:02d}"
    w = text_width(draw, txt, f)
    draw.text((W - 60 - w, H - 60), txt, fill=MUTED, font=f)


def detected_label(draw, x, y, confidence, color=ACCENT):
    f = font_mono(20)
    draw.text((x, y), f"DETECTED  {confidence}", fill=color, font=f)


def base_portrait():
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)
    # subtle crosshair as background motif
    draw.line([(0, H // 2), (W, H // 2)], fill=DIM_RED, width=1)
    draw.line([(W // 2, 0), (W // 2, H)], fill=DIM_RED, width=1)
    return img, draw, W, H


def base_story():
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)
    draw.line([(0, H // 2), (W, H // 2)], fill=DIM_RED, width=2)
    draw.line([(W // 2, 0), (W // 2, H)], fill=DIM_RED, width=2)
    return img, draw, W, H


# -------------------- CAROUSEL: The Blind Spot (6 slides) -------------------- #

def carousel_slide_1():
    img, draw, W, H = base_portrait()
    f_label = font_mono(22)
    f_huge = font(110, bold=True)
    f_sub = font(36)

    draw.text((60, 100), "THE BLIND SPOT", fill=ACCENT, font=f_label)
    draw_wordmark(draw, 60, 145, size=22, color=MUTED)

    y = 420
    for line in ["Your brand", "monitoring tool", "sees about"]:
        draw.text((60, y), line, fill=WHITE, font=f_huge)
        y += 125

    # Big 20% accent
    f_pct = font(280, bold=True)
    draw.text((60, 850), "20%", fill=ACCENT, font=f_pct)

    draw.text((60, 1180), "of your actual mentions.", fill=MUTED, font=f_sub)

    page_number(draw, 1, 6, W, H)
    out = OUT / "tue-carousel-01.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def carousel_slide_2():
    img, draw, W, H = base_portrait()
    f_huge = font(96, bold=True)
    f_med = font(40)

    # Stacked statement
    y = 280
    for line, color in [
        ("Hashtags are", WHITE),
        ("the minority.", WHITE),
        ("", WHITE),
        ("Pixels are", WHITE),
        ("the majority.", ACCENT),
    ]:
        draw.text((60, y), line, fill=color, font=f_huge)
        y += 120

    draw.text((60, 1180), "And nobody sees them.", fill=MUTED, font=f_med)

    page_number(draw, 2, 6, W, H)
    out = OUT / "tue-carousel-02.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def carousel_slide_3():
    """Show a 'caught' detection — anonymized."""
    img, draw, W, H = base_portrait()
    f_label = font_mono(22)
    f_head = font(76, bold=True)
    f_body = font(36)

    draw.text((60, 100), "DETECTED  0.94", fill=ACCENT, font=f_label)

    # Placeholder content area with dashed bbox
    box_x, box_y, box_w, box_h = 90, 280, 900, 600
    draw.rectangle([(box_x, box_y), (box_x + box_w, box_y + box_h)], fill=SOFT_GRAY)
    draw_dashed_rect(draw, box_x + 80, box_y + 80, box_w - 160, box_h - 160, ACCENT, stroke=5, dash=30, gap=18)

    f_mini = font_mono(24)
    txt = "[ product in image ]"
    w = text_width(draw, txt, f_mini)
    draw.text((box_x + (box_w - w) // 2, box_y + box_h // 2 - 12), txt, fill=MUTED, font=f_mini)

    # Below: caption
    y = 980
    for line in [
        "No hashtag.",
        "No @mention.",
        "Just a product in someone's hand.",
    ]:
        draw.text((60, y), line, fill=WHITE, font=f_head if "@mention" not in line and "Just" not in line else f_body)
        y += 80 if "Just" not in line and "@mention" not in line else 0

    # Re-render cleanly
    img2, draw2, _, _ = base_portrait()
    draw2.text((60, 100), "DETECTED  0.94", fill=ACCENT, font=f_label)
    draw2.rectangle([(box_x, box_y), (box_x + box_w, box_y + box_h)], fill=SOFT_GRAY)
    draw_dashed_rect(draw2, box_x + 80, box_y + 80, box_w - 160, box_h - 160, ACCENT, stroke=5, dash=30, gap=18)
    draw2.text((box_x + (box_w - w) // 2, box_y + box_h // 2 - 12), txt, fill=MUTED, font=f_mini)
    f_l1 = font(64, bold=True)
    f_l2 = font(42)
    draw2.text((60, 950), "No hashtag.", fill=WHITE, font=f_l1)
    draw2.text((60, 1030), "No @mention.", fill=WHITE, font=f_l1)
    draw2.text((60, 1130), "Just your product in someone's hand.", fill=MUTED, font=f_l2)

    page_number(draw2, 3, 6, W, H)
    out = OUT / "tue-carousel-03.png"
    img2.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def carousel_slide_4():
    img, draw, W, H = base_portrait()
    f_head = font(72, bold=True)
    f_body = font(38)

    draw.text((60, 220), "Tagging is dead.", fill=ACCENT, font=f_head)
    draw.text((60, 320), "Posting is not.", fill=WHITE, font=f_head)

    lines = [
        "Creators show your product",
        "in the frame — and don't tag.",
        "",
        "Festivals, kitchens, sofas, cars.",
        "Half-second flashes in reels.",
        "Quiet shelves in vlogs.",
        "",
        "Your tool still searches text.",
        "Your real footprint is visual.",
    ]
    y = 540
    for line in lines:
        col = WHITE if line and not line.startswith("Your") else (MUTED if line.startswith("Your") else WHITE)
        if not line:
            y += 18
            continue
        draw.text((60, y), line, fill=col, font=f_body)
        y += 56

    page_number(draw, 4, 6, W, H)
    out = OUT / "tue-carousel-04.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def carousel_slide_5():
    img, draw, W, H = base_portrait()
    f_huge = font(96, bold=True)
    f_med = font(38)

    draw.text((60, 220), "We see", fill=WHITE, font=f_huge)
    draw.text((60, 340), "what your", fill=WHITE, font=f_huge)
    draw.text((60, 460), "social tool", fill=WHITE, font=f_huge)
    draw.text((60, 580), "misses.", fill=ACCENT, font=f_huge)

    lines = [
        "Computer vision scans",
        "Instagram and TikTok for",
        "your product in every image.",
        "",
        "Daily. Automatically.",
        "First hits in 24 hours.",
    ]
    y = 800
    for line in lines:
        if not line:
            y += 20
            continue
        draw.text((60, y), line, fill=MUTED if "Daily" in line or "First" in line else WHITE, font=f_med)
        y += 56

    page_number(draw, 5, 6, W, H)
    out = OUT / "tue-carousel-05.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def carousel_slide_6():
    img, draw, W, H = base_portrait()
    f_huge = font(110, bold=True)
    f_body = font(42)
    f_url = font_mono(36)

    draw.text((60, 240), "Try it on", fill=WHITE, font=f_huge)
    draw.text((60, 360), "your brand.", fill=ACCENT, font=f_huge)

    draw.text((60, 600), "Free 14-day trial.", fill=WHITE, font=f_body)
    draw.text((60, 660), "First detections within 24h.", fill=MUTED, font=f_body)
    draw.text((60, 720), "No card required.", fill=MUTED, font=f_body)

    # CTA box
    box_x, box_y, box_w, box_h = 60, 900, 960, 180
    draw_dashed_rect(draw, box_x, box_y, box_w, box_h, ACCENT, stroke=5, dash=30, gap=18)
    txt = "spotyourbrand.com"
    f_cta = font(58, bold=True)
    w = text_width(draw, txt, f_cta)
    draw.text((box_x + (box_w - w) // 2, box_y + 60), txt, fill=ACCENT, font=f_cta)

    wordmark_centered(draw, H - 120, W, size=28, color=WHITE)

    page_number(draw, 6, 6, W, H)
    out = OUT / "tue-carousel-06.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


# -------------------- STORIES: Wed Poll Sequence (5 frames) -------------------- #

def story_frame_1():
    img, draw, W, H = base_story()
    f_label = font_mono(28)
    f_huge = font(98, bold=True)

    draw.text((80, 200), "QUICK ONE", fill=ACCENT, font=f_label)
    draw.text((80, 240), "FOR BRAND TEAMS", fill=ACCENT, font=f_label)

    y = 700
    for line in [
        "How much of",
        "your brand's",
        "social mentions",
        "does your tool",
        "actually see?",
    ]:
        draw.text((80, y), line, fill=WHITE, font=f_huge)
        y += 115

    wordmark_centered(draw, H - 140, W, size=32, color=MUTED)
    out = OUT / "wed-story-01.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def story_frame_2():
    """Poll placeholder. Real IG poll sticker is added in-app on upload."""
    img, draw, W, H = base_story()
    f_med = font(54, bold=True)
    f_small = font_mono(24)

    draw.text((80, 380), "Add the poll", fill=MUTED, font=f_small)
    draw.text((80, 420), "sticker here in IG:", fill=MUTED, font=f_small)

    options = [
        ("<20%", ACCENT),
        ("20-50%", WHITE),
        ("50-80%", WHITE),
        (">80%", WHITE),
    ]
    y = 700
    for label, col in options:
        box_y = y
        draw.rectangle([(80, box_y), (W - 80, box_y + 160)], outline=col, width=4)
        draw.text((130, box_y + 50), label, fill=col, font=f_med)
        y += 200

    wordmark_centered(draw, H - 140, W, size=32, color=MUTED)
    out = OUT / "wed-story-02.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def story_frame_3():
    img, draw, W, H = base_story()
    f_label = font_mono(28)
    f_huge = font(110, bold=True)
    f_body = font(46)

    draw.text((80, 200), "SPOILER", fill=ACCENT, font=f_label)

    y = 600
    for line, col in [
        ("Most brands", WHITE),
        ("we audit are", WHITE),
        ("under 20%.", ACCENT),
    ]:
        draw.text((80, y), line, fill=col, font=f_huge)
        y += 130

    draw.text((80, 1100), "The other 80%", fill=MUTED, font=f_body)
    draw.text((80, 1160), "is in pixels, not text.", fill=MUTED, font=f_body)

    wordmark_centered(draw, H - 140, W, size=32, color=MUTED)
    out = OUT / "wed-story-03.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def story_frame_4():
    img, draw, W, H = base_story()
    f_huge = font(94, bold=True)
    f_body = font(42)

    y = 400
    for line in [
        "Computer vision",
        "finds your product",
        "in the image.",
        "",
        "Daily.",
        "Automatically.",
    ]:
        if not line:
            y += 30
            continue
        col = ACCENT if "Daily" in line or "Automatically" in line else WHITE
        f = f_huge if line in ("Daily.", "Automatically.") else f_huge
        draw.text((80, y), line, fill=col, font=f)
        y += 130

    # Mini detection demo
    bx, by, bw, bh = 200, 1380, 680, 340
    draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=SOFT_GRAY)
    draw_dashed_rect(draw, bx + 60, by + 60, bw - 120, bh - 120, ACCENT, stroke=4, dash=24, gap=14)
    detected_label(draw, bx, by - 36, "0.96", color=ACCENT)
    f_m = font_mono(22)
    txt = "[ product ]"
    w = text_width(draw, txt, f_m)
    draw.text((bx + (bw - w) // 2, by + bh // 2 - 10), txt, fill=MUTED, font=f_m)

    wordmark_centered(draw, H - 140, W, size=32, color=MUTED)
    out = OUT / "wed-story-04.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def story_frame_5():
    img, draw, W, H = base_story()
    f_huge = font(118, bold=True)
    f_body = font(48)
    f_url = font_mono(44)

    draw.text((80, 380), "Try it on", fill=WHITE, font=f_huge)
    draw.text((80, 520), "your brand.", fill=ACCENT, font=f_huge)

    draw.text((80, 800), "Free 14-day trial.", fill=WHITE, font=f_body)
    draw.text((80, 870), "No card required.", fill=MUTED, font=f_body)

    # Big CTA box for the link sticker overlay
    box_x, box_y, box_w, box_h = 80, 1100, W - 160, 240
    draw_dashed_rect(draw, box_x, box_y, box_w, box_h, ACCENT, stroke=6, dash=34, gap=20)
    txt = "spotyourbrand.com"
    w = text_width(draw, txt, f_url)
    draw.text((box_x + (box_w - w) // 2, box_y + 95), txt, fill=ACCENT, font=f_url)
    f_hint = font_mono(20)
    hint = "↑ ADD LINK STICKER HERE"
    w = text_width(draw, hint, f_hint)
    draw.text((box_x + (box_w - w) // 2, box_y + box_h + 20), hint, fill=MUTED, font=f_hint)

    wordmark_centered(draw, H - 140, W, size=32, color=WHITE)
    out = OUT / "wed-story-05.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


# -------------------- GRID FILLERS: 4 standalone posts -------------------- #

def grid_post_stat_split():
    """20 / 80 stat reveal — visual split."""
    img, draw, W, H = base_portrait()
    f_label = font_mono(24)
    f_pct = font(360, bold=True)
    f_body = font(44)

    draw.text((60, 100), "THE GAP", fill=ACCENT, font=f_label)

    # 20%
    draw.text((60, 280), "20%", fill=MUTED, font=f_pct)
    draw.text((60, 660), "you see", fill=MUTED, font=f_body)

    # divider
    draw.line([(60, 760), (W - 60, 760)], fill=DIM_RED, width=2)

    # 80%
    draw.text((60, 800), "80%", fill=ACCENT, font=f_pct)
    draw.text((60, 1180), "you don't.", fill=WHITE, font=f_body)

    wordmark_centered(draw, H - 70, W, size=22, color=MUTED)
    out = OUT / "grid-stat-split.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def grid_post_manifesto():
    """Brands live in pixels."""
    img, draw, W, H = base_portrait()
    f_huge = font(96, bold=True)
    f_body = font(38)

    y = 280
    for line, col in [
        ("Brands don't live", WHITE),
        ("in hashtags.", MUTED),
        ("", WHITE),
        ("They live in", WHITE),
        ("pixels.", ACCENT),
    ]:
        if not line:
            y += 40
            continue
        draw.text((60, y), line, fill=col, font=f_huge)
        y += 115

    draw.text((60, 1080), "Spot the Brand finds them.", fill=WHITE, font=f_body)
    draw.text((60, 1140), "All of them.", fill=MUTED, font=f_body)

    wordmark_centered(draw, H - 70, W, size=22, color=MUTED)
    out = OUT / "grid-manifesto.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def grid_post_definition():
    """A dictionary-style definition card."""
    img, draw, W, H = base_portrait()
    f_label = font_mono(26)
    f_word = font(140, bold=True)
    f_pos = font_mono(28)
    f_def = font(40)

    draw.text((60, 100), "DEFINITION", fill=ACCENT, font=f_label)

    draw.text((60, 240), "blind spot", fill=WHITE, font=f_word)
    draw.text((60, 410), "/blʌɪnd spɒt/", fill=MUTED, font=f_pos)
    draw.text((60, 460), "noun", fill=MUTED, font=f_pos)

    lines = [
        "1.  The 80% of your brand's social",
        "    mentions invisible to your",
        "    monitoring tool because they",
        "    have no hashtag, no @mention,",
        "    just your product in the frame.",
        "",
        "2.  What Spot the Brand finds.",
    ]
    y = 600
    for line in lines:
        if not line:
            y += 20
            continue
        col = ACCENT if line.startswith("2.") else WHITE
        draw.text((60, y), line, fill=col, font=f_def)
        y += 58

    wordmark_centered(draw, H - 70, W, size=22, color=MUTED)
    out = OUT / "grid-definition.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def grid_post_detection_demo():
    """Single-frame anonymized detection example for the grid."""
    img, draw, W, H = base_portrait()
    f_label = font_mono(22)
    f_head = font(72, bold=True)
    f_body = font(36)

    # Header strip
    draw.text((60, 100), "DETECTED  0.97", fill=ACCENT, font=f_label)
    draw.text((60, 132), "instagram · reel · NL", fill=MUTED, font=f_label)

    # Mock content frame
    bx, by, bw, bh = 90, 240, 900, 720
    draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=SOFT_GRAY)
    draw_dashed_rect(draw, bx + 220, by + 200, 460, 320, ACCENT, stroke=6, dash=32, gap=18)
    f_m = font_mono(24)
    txt = "[ product ]"
    w = text_width(draw, txt, f_m)
    draw.text((bx + 220 + (460 - w) // 2, by + 200 + 320 // 2 - 12), txt, fill=MUTED, font=f_m)

    # Footer
    draw.text((60, 1010), "Zero hashtags.", fill=WHITE, font=f_head)
    draw.text((60, 1090), "Zero @mentions.", fill=WHITE, font=f_head)
    draw.text((60, 1190), "Found anyway.", fill=ACCENT, font=f_body)

    wordmark_centered(draw, H - 70, W, size=22, color=MUTED)
    out = OUT / "grid-detection-demo.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


def grid_post_principle():
    """One-line principle post — punchy."""
    img, draw, W, H = base_portrait()
    f_label = font_mono(26)
    f_huge = font(88, bold=True)
    f_sub = font(36)

    draw.text((60, 100), "PRINCIPLE  001", fill=ACCENT, font=f_label)

    y = 380
    for line, col in [
        ("If your tool", WHITE),
        ("can't see it,", WHITE),
        ("it didn't", WHITE),
        ("happen.", ACCENT),
    ]:
        draw.text((60, y), line, fill=col, font=f_huge)
        y += 110

    draw.text((60, 980), "We see the things your", fill=MUTED, font=f_sub)
    draw.text((60, 1030), "monitoring tool can't.", fill=MUTED, font=f_sub)
    draw.text((60, 1110), "Visual brand monitoring.", fill=WHITE, font=f_sub)

    wordmark_centered(draw, H - 70, W, size=22, color=MUTED)
    out = OUT / "grid-principle.png"
    img.save(out, "PNG", optimize=True)
    print(f"Wrote {out.name}")


# -------------------- MAIN -------------------- #

if __name__ == "__main__":
    print("Building Tuesday carousel...")
    carousel_slide_1()
    carousel_slide_2()
    carousel_slide_3()
    carousel_slide_4()
    carousel_slide_5()
    carousel_slide_6()

    print("\nBuilding Wednesday story sequence...")
    story_frame_1()
    story_frame_2()
    story_frame_3()
    story_frame_4()
    story_frame_5()

    print("\nBuilding grid-filler posts...")
    grid_post_stat_split()
    grid_post_manifesto()
    grid_post_definition()
    grid_post_detection_demo()
    grid_post_principle()

    print(f"\nAll organic posts written to {OUT}")
