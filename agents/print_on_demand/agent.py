"""
Print-on-Demand Design Agent
Generates typography-based POD designs with Pillow and Claude-generated metadata.
"""

import sys
import json
import math
import random
from pathlib import Path
from datetime import datetime

# Allow importing from shared/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import (
    slugify, fetch_reddit_titles, save_text, save_json, today_dir, datestamp
)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False
    print("[WARN] Pillow not installed — PNG generation disabled")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "print_on_demand"
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs" / "designs"
STATE_FILE = DATA_DIR / "pod_state.json"

CANVAS_SIZE = (800, 800)

CURATED_THEMES = [
    "cottagecore",
    "dark academia",
    "Y2K aesthetic",
    "mental health awareness",
    "retro gaming",
    "astronomy and space",
    "plant mom",
    "feminist empowerment",
    "cat lover",
    "dog lover",
    "solarpunk",
    "witchy vibes",
    "ocean cottagecore",
    "goblincore",
    "vaporwave nostalgia",
    "mushroom forager",
    "frog appreciation",
    "stargazer aesthetic",
    "bookworm life",
    "hiking and outdoors",
]

REDDIT_SOURCES = ["redbubble", "Etsy", "tshirtdesigns"]

SYSTEM_PROMPT = (
    "You are a professional print-on-demand designer with deep knowledge of "
    "trending Redbubble and Etsy markets. You produce concise, commercially "
    "viable designs that sell well. Always respond with valid JSON only — "
    "no markdown, no extra commentary."
)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"used_themes": [], "total_designs": 0, "runs": []}


def save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Theme selection
# ---------------------------------------------------------------------------

def gather_trending_themes() -> list[str]:
    """Pull Reddit hot titles and combine with curated list."""
    reddit_titles: list[str] = []
    for sub in REDDIT_SOURCES:
        titles = fetch_reddit_titles(sub, limit=10)
        reddit_titles.extend(titles)

    theme_pool = list(CURATED_THEMES)

    # Extract keywords from Reddit titles as additional theme hints
    reddit_hints: list[str] = []
    keywords = [
        "cottagecore", "dark academia", "y2k", "mental health", "retro",
        "space", "plant", "feminist", "cat", "dog", "mushroom", "frog",
        "witch", "ocean", "vintage", "aesthetic", "nature", "gaming",
    ]
    for title in reddit_titles:
        lower = title.lower()
        for kw in keywords:
            if kw in lower and kw not in reddit_hints:
                reddit_hints.append(kw)

    if reddit_hints:
        theme_pool = reddit_hints + theme_pool

    return theme_pool


def pick_themes(theme_pool: list[str], used: list[str], n: int = 3) -> list[str]:
    """Choose n themes not recently used."""
    available = [t for t in theme_pool if t not in used[-30:]]
    if len(available) < n:
        available = theme_pool  # reset if exhausted
    return random.sample(available, min(n, len(available)))


# ---------------------------------------------------------------------------
# Claude: generate design concept
# ---------------------------------------------------------------------------

def generate_concept(theme: str) -> dict:
    """Ask Claude to produce full design metadata for a theme."""
    prompt = f"""Create a print-on-demand design concept for the theme: "{theme}".

Return a JSON object with exactly these keys:
{{
  "theme": "{theme}",
  "design_title": "catchy 3-6 word design title",
  "main_text": "the primary quote or phrase (max 6 words, bold statement)",
  "sub_text": "secondary line (max 8 words, softer complement)",
  "font_style": "description of font personality (e.g. 'serif with elegant thin strokes')",
  "color_palette": [
    {{"name": "color name", "hex": "#RRGGBB"}},
    {{"name": "color name", "hex": "#RRGGBB"}},
    {{"name": "color name", "hex": "#RRGGBB"}},
    {{"name": "color name", "hex": "#RRGGBB"}}
  ],
  "product_titles": {{
    "t_shirt": "SEO title for t-shirt listing",
    "hoodie": "SEO title for hoodie listing",
    "mug": "SEO title for mug listing",
    "phone_case": "SEO title for phone case listing",
    "sticker": "SEO title for sticker listing"
  }},
  "redbubble_tags": [
    "tag1", "tag2", "tag3", "tag4", "tag5",
    "tag6", "tag7", "tag8", "tag9", "tag10",
    "tag11", "tag12", "tag13", "tag14", "tag15",
    "tag16", "tag17", "tag18", "tag19", "tag20"
  ],
  "design_description": "2-sentence product description for listings"
}}

Rules:
- main_text should be short enough to display on a shirt (max 30 chars preferred)
- color_palette: first color = background, last color = main text color
- all 20 tags must be unique, relevant, mix of broad and niche
- font_style: pick from serif / sans-serif / script / display / monospace + personality descriptors"""

    return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=1200, smart=True)


# ---------------------------------------------------------------------------
# Pillow: render design PNG
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple[int, int, int]:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def draw_gradient_bg(draw: "ImageDraw.ImageDraw", w: int, h: int,
                     top_color: tuple, bottom_color: tuple):
    for y in range(h):
        t = y / h
        r, g, b = lerp_color(top_color, bottom_color, t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def draw_decorative_circles(draw: "ImageDraw.ImageDraw", w: int, h: int,
                             accent_rgb: tuple, count: int = 6):
    """Scatter translucent decorative circles around the canvas."""
    for _ in range(count):
        cx = random.randint(0, w)
        cy = random.randint(0, h)
        r = random.randint(20, 80)
        # Use a slightly transparent version by layering
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(*accent_rgb, 60),
            width=2,
        )


def draw_corner_lines(draw: "ImageDraw.ImageDraw", w: int, h: int,
                      color_rgb: tuple, margin: int = 40):
    """Draw elegant corner bracket lines."""
    length = 60
    lw = 2
    c = (*color_rgb,)
    # Top-left
    draw.line([(margin, margin), (margin + length, margin)], fill=c, width=lw)
    draw.line([(margin, margin), (margin, margin + length)], fill=c, width=lw)
    # Top-right
    draw.line([(w - margin - length, margin), (w - margin, margin)], fill=c, width=lw)
    draw.line([(w - margin, margin), (w - margin, margin + length)], fill=c, width=lw)
    # Bottom-left
    draw.line([(margin, h - margin - length), (margin, h - margin)], fill=c, width=lw)
    draw.line([(margin, h - margin), (margin + length, h - margin)], fill=c, width=lw)
    # Bottom-right
    draw.line([(w - margin, h - margin - length), (w - margin, h - margin)], fill=c, width=lw)
    draw.line([(w - margin - length, h - margin), (w - margin, h - margin)], fill=c, width=lw)


def draw_horizontal_dividers(draw: "ImageDraw.ImageDraw", w: int, h: int,
                              y_pos: int, color_rgb: tuple):
    """Draw a short decorative line divider centered horizontally."""
    line_w = 120
    cx = w // 2
    lw = 1
    draw.line([(cx - line_w, y_pos), (cx + line_w, y_pos)],
              fill=(*color_rgb,), width=lw)
    # Small diamond at center
    d = 4
    draw.polygon([
        (cx, y_pos - d),
        (cx + d, y_pos),
        (cx, y_pos + d),
        (cx - d, y_pos),
    ], fill=(*color_rgb,))


def get_font(size: int) -> "ImageFont.FreeTypeFont":
    """Try common system fonts; fall back to default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def get_font_regular(size: int) -> "ImageFont.FreeTypeFont":
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def render_design(concept: dict, out_path_colored: Path, out_path_transparent: Path):
    """Create two 800x800 PNGs: one with colored BG, one with transparent BG."""
    if not PILLOW_OK:
        print(f"  [SKIP] Pillow unavailable — skipping PNG generation")
        return

    palette = concept.get("color_palette", [])
    while len(palette) < 4:
        palette.append({"name": "white", "hex": "#FFFFFF"})

    bg_rgb = hex_to_rgb(palette[0]["hex"])
    bg2_rgb = hex_to_rgb(palette[1]["hex"])
    accent_rgb = hex_to_rgb(palette[2]["hex"])
    text_rgb = hex_to_rgb(palette[-1]["hex"])

    main_text = concept.get("main_text", "BE YOURSELF")
    sub_text = concept.get("sub_text", "always and forever")
    w, h = CANVAS_SIZE

    # ---- Colored background version ----------------------------------------
    img_c = Image.new("RGB", (w, h), bg_rgb)
    draw_c = ImageDraw.Draw(img_c)

    # Gradient background
    draw_gradient_bg(draw_c, w, h, bg_rgb, bg2_rgb)

    # Decorative background circles (subtle)
    random.seed(main_text)  # deterministic per design
    draw_decorative_circles(draw_c, w, h, accent_rgb, count=8)

    # Corner brackets
    draw_corner_lines(draw_c, w, h, accent_rgb, margin=35)

    # Fonts
    main_font_size = 72
    main_font = get_font(main_font_size)
    sub_font = get_font_regular(32)
    tiny_font = get_font_regular(18)

    # Wrap and measure main text
    max_text_w = int(w * 0.78)
    main_lines = wrap_text(main_text.upper(), main_font, max_text_w, draw_c)

    line_h = main_font_size + 12
    total_main_h = len(main_lines) * line_h
    main_start_y = h // 2 - total_main_h // 2 - 40

    # Draw main text (slight shadow)
    shadow_offset = 3
    for i, line in enumerate(main_lines):
        bbox = draw_c.textbbox((0, 0), line, font=main_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        y = main_start_y + i * line_h
        # Shadow
        draw_c.text((x + shadow_offset, y + shadow_offset), line,
                    font=main_font, fill=(*accent_rgb, 80))
        # Main text
        draw_c.text((x, y), line, font=main_font, fill=text_rgb)

    # Divider line
    divider_y = main_start_y + total_main_h + 20
    draw_horizontal_dividers(draw_c, w, h, divider_y, accent_rgb)

    # Sub text
    sub_lines = wrap_text(sub_text, sub_font, max_text_w, draw_c)
    sub_start_y = divider_y + 30
    for i, line in enumerate(sub_lines):
        bbox = draw_c.textbbox((0, 0), line, font=sub_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        y = sub_start_y + i * 40
        draw_c.text((x, y), line, font=sub_font, fill=accent_rgb)

    # Small theme label at bottom
    theme_label = concept.get("theme", "").upper()
    bbox = draw_c.textbbox((0, 0), theme_label, font=tiny_font)
    lw = bbox[2] - bbox[0]
    draw_c.text(((w - lw) // 2, h - 55), theme_label,
                font=tiny_font, fill=(*accent_rgb,))

    out_path_colored.parent.mkdir(parents=True, exist_ok=True)
    img_c.save(str(out_path_colored), "PNG", dpi=(300, 300))

    # ---- Transparent background version ------------------------------------
    img_t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_t = ImageDraw.Draw(img_t)

    # Corner brackets in accent color
    draw_corner_lines(draw_t, w, h, accent_rgb, margin=35)

    # Main text (use dark color for visibility on transparent)
    render_color = text_rgb if sum(text_rgb) < 400 else bg_rgb
    for i, line in enumerate(main_lines):
        bbox = draw_t.textbbox((0, 0), line, font=main_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        y = main_start_y + i * line_h
        draw_t.text((x, y), line, font=main_font, fill=(*render_color, 255))

    draw_horizontal_dividers(draw_t, w, h, divider_y, accent_rgb)

    for i, line in enumerate(sub_lines):
        bbox = draw_t.textbbox((0, 0), line, font=sub_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        y = sub_start_y + i * 40
        draw_t.text((x, y), line, font=sub_font, fill=(*accent_rgb, 230))

    draw_t.text(((w - draw_t.textbbox((0, 0), theme_label, font=tiny_font)[2]) // 2,
                  h - 55),
                theme_label, font=tiny_font, fill=(*accent_rgb, 200))

    img_t.save(str(out_path_transparent), "PNG", dpi=(300, 300))
    print(f"  Saved: {out_path_colored.name} + transparent variant")


# ---------------------------------------------------------------------------
# Upload guide
# ---------------------------------------------------------------------------

UPLOAD_TEMPLATE = """\
REDBUBBLE UPLOAD GUIDE — Generated {date}
===========================================

HOW TO UPLOAD:
1. Go to https://www.redbubble.com and log in.
2. Click "Add New Work" (top right).
3. Upload the colored PNG file first, then the transparent PNG for merch that
   needs a transparent background (stickers, masks).
4. Copy the design title and tags below into the listing form.
5. Enable ALL product types initially; disable low-margin ones later.
6. Set pricing at 20% markup to start; adjust based on performance.

---
{designs}
---

GENERAL TIPS:
- Use ALL 20 tags — Redbubble uses them for search ranking.
- Keep your description under 500 characters for best SEO.
- Add designs to relevant Groups in Redbubble after uploading.
- Post to Pinterest / Instagram Reels for extra traffic.
"""

DESIGN_BLOCK = """\
DESIGN #{num}: {design_title}
Theme: {theme}
Files: {slug}_colored.png  |  {slug}_transparent.png

T-SHIRT TITLE:
  {t_shirt}

HOODIE TITLE:
  {hoodie}

MUG TITLE:
  {mug}

PHONE CASE TITLE:
  {phone_case}

STICKER TITLE:
  {sticker}

DESCRIPTION:
  {design_description}

TAGS (copy all):
  {tags}

COLORS: {color_names}
"""


def build_upload_guide(concepts: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(concepts, 1):
        pt = c.get("product_titles", {})
        tags_str = ", ".join(c.get("redbubble_tags", []))
        color_names = ", ".join(p.get("name", "") for p in c.get("color_palette", []))
        slug = slugify(c.get("design_title", f"design-{i}"))
        block = DESIGN_BLOCK.format(
            num=i,
            design_title=c.get("design_title", ""),
            theme=c.get("theme", ""),
            slug=slug,
            t_shirt=pt.get("t_shirt", ""),
            hoodie=pt.get("hoodie", ""),
            mug=pt.get("mug", ""),
            phone_case=pt.get("phone_case", ""),
            sticker=pt.get("sticker", ""),
            design_description=c.get("design_description", ""),
            tags=tags_str,
            color_names=color_names,
        )
        blocks.append(block)
    return UPLOAD_TEMPLATE.format(
        date=datestamp(),
        designs="\n".join(blocks),
    )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run():
    print(f"\n[POD Agent] Starting run — {datestamp()}")

    state = load_state()
    theme_pool = gather_trending_themes()
    selected_themes = pick_themes(theme_pool, state.get("used_themes", []), n=3)
    print(f"  Themes selected: {selected_themes}")

    out_dir = today_dir(OUTPUTS_DIR)
    concepts: list[dict] = []

    for theme in selected_themes:
        print(f"\n  Generating concept for: {theme}")
        try:
            concept = generate_concept(theme)
        except Exception as e:
            print(f"  [ERROR] Claude generation failed for '{theme}': {e}")
            continue

        slug = slugify(concept.get("design_title", theme))
        colored_path = out_dir / f"{slug}_colored.png"
        transparent_path = out_dir / f"{slug}_transparent.png"

        render_design(concept, colored_path, transparent_path)
        concept["files"] = {
            "colored": str(colored_path),
            "transparent": str(transparent_path),
        }
        concepts.append(concept)

        # Track in revenue system
        log_output(
            AGENT_NAME,
            concept.get("design_title", theme),
            str(colored_path),
            notes=f"theme={theme}, tags={len(concept.get('redbubble_tags', []))}",
        )

    if not concepts:
        print("  [WARN] No concepts generated — exiting.")
        return

    # Save designs.json
    designs_json_path = out_dir / "designs.json"
    save_json(designs_json_path, {"date": datestamp(), "designs": concepts})
    print(f"\n  Saved designs.json -> {designs_json_path}")

    # Save upload guide
    guide_path = out_dir / "redbubble_upload_guide.txt"
    guide_text = build_upload_guide(concepts)
    save_text(guide_path, guide_text)
    print(f"  Saved upload guide -> {guide_path}")

    # Update state
    state["used_themes"].extend(selected_themes)
    state["total_designs"] = state.get("total_designs", 0) + len(concepts)
    state["runs"].append({
        "date": datestamp(),
        "themes": selected_themes,
        "designs_created": len(concepts),
        "output_dir": str(out_dir),
    })
    save_state(state)

    print(f"\n[POD Agent] Done. Created {len(concepts)} designs in {out_dir}\n")


if __name__ == "__main__":
    run()
