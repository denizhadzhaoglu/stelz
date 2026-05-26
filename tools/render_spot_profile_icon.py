"""Render Spot the Brand profile picture as 1080x1080 PNG for Instagram.

Uses the variant-03 (app icon) design from logo-concepts.svg: solid Spot Red
square with a thin dashed white bounding-box outline + small white dot, all
fully bleed to fill IG's circular crop.
"""
from PIL import Image, ImageDraw
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "projects" / "spot-the-brand" / "assets" / "profile-icon-1080.png"
SIZE = 1080
ACCENT = (255, 19, 0)
WHITE = (255, 255, 255)

img = Image.new("RGB", (SIZE, SIZE), ACCENT)
draw = ImageDraw.Draw(img)

# Inner dashed bounding box — sits within the safe circle of IG's crop
box_size = int(SIZE * 0.55)
box_x = (SIZE - box_size) // 2
box_y = (SIZE - box_size) // 2
stroke_width = 14

# Simulate dashed stroke via short line segments along each side
dash_len = 32
gap_len = 18
period = dash_len + gap_len

def draw_dashed_line(draw, p1, p2, color, width):
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        # vertical
        y = min(y1, y2)
        end = max(y1, y2)
        while y < end:
            ny = min(y + dash_len, end)
            draw.line([(x1, y), (x1, ny)], fill=color, width=width)
            y = ny + gap_len
    else:
        x = min(x1, x2)
        end = max(x1, x2)
        while x < end:
            nx = min(x + dash_len, end)
            draw.line([(x, y1), (nx, y1)], fill=color, width=width)
            x = nx + gap_len

draw_dashed_line(draw, (box_x, box_y), (box_x + box_size, box_y), WHITE, stroke_width)
draw_dashed_line(draw, (box_x, box_y + box_size), (box_x + box_size, box_y + box_size), WHITE, stroke_width)
draw_dashed_line(draw, (box_x, box_y), (box_x, box_y + box_size), WHITE, stroke_width)
draw_dashed_line(draw, (box_x + box_size, box_y), (box_x + box_size, box_y + box_size), WHITE, stroke_width)

# Small white dot center
dot_r = int(SIZE * 0.045)
cx, cy = SIZE // 2, SIZE // 2
draw.ellipse([(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)], fill=WHITE)

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, "PNG", optimize=True)
print(f"Wrote {OUT}")
print(f"Size: {SIZE}x{SIZE}, file ~{OUT.stat().st_size // 1024}KB")
