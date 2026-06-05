"""
Print-on-Demand Design Agent
Generates typography-based POD designs with Pillow and Claude-generated metadata.
"""

import os
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

CANVAS_SIZE = (4500, 4500)   # print-quality: 15×15 in @ 300 DPI

# Brand constants
BRAND_BG      = (13, 13, 13)       # near-black background
BRAND_WHITE   = (255, 255, 255)    # pure white text
BRAND_GOLD    = (201, 168, 76)     # gold accent #C9A84C
BRAND_DIMGOLD = (140, 117, 53)     # dimmer gold for sub elements
BRAND_GRAY    = (80, 80, 80)       # subtle brand mark color

# BRAND: RISE SUPPLY CO. — Motivational/Mindset niche
# Proven #1 POD earner. Bold dark aesthetic. Max revenue focus.
BRAND_NAME  = "RISE SUPPLY CO."
BRAND_NICHE = "motivational mindset"

CURATED_THEMES = [
    # Core motivational — highest search volume
    "stoic philosophy",
    "self discipline",
    "grind and hustle",
    "mental toughness",
    "winners mindset",
    "silent hard work",
    "discipline over motivation",
    "delayed gratification",
    "no excuses mentality",
    "build your empire",
    # Lifestyle/identity
    "early riser 5am club",
    "gym and fitness mindset",
    "entrepreneur grind",
    "be the wolf not the sheep",
    "stay dangerous stay humble",
    "pressure makes diamonds",
    "control what you can control",
    "do it scared anyway",
    "your only competition is yesterday",
    "outwork everyone",
]

REDDIT_SOURCES = ["getmotivated", "EntrepreneurRideAlong", "Entrepreneur"]

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
    prompt = f"""Create a HIGH-CONVERTING print-on-demand design for RISE SUPPLY CO., a motivational/mindset brand.

Theme: "{theme}"

BRAND RULES — follow exactly:
- Bold, dark aesthetic: deep black or near-black background (#0a0a0a, #111111, #1a1a1a) + white or gold text
- Main text = punchy, emotionally charged quote (4-7 words MAX, all caps preferred)
- Sub text = short supporting line that adds depth (max 8 words)
- Font = bold geometric sans-serif or strong condensed display — conveys power
- Designs must look great on black t-shirts and white mugs
- Target audience: 18-35 male and female, driven, ambitious, gym-goers, entrepreneurs

Return ONLY a JSON object with exactly these keys:
{{
  "theme": "{theme}",
  "design_title": "3-5 word brand-aligned title",
  "main_text": "THE BOLD QUOTE (ALL CAPS, max 7 words)",
  "sub_text": "supporting line max 8 words",
  "font_style": "bold geometric sans-serif, high contrast, strong weight",
  "color_palette": [
    {{"name": "background", "hex": "#111111"}},
    {{"name": "primary text", "hex": "#FFFFFF"}},
    {{"name": "accent gold", "hex": "#C9A84C"}},
    {{"name": "secondary", "hex": "#888888"}}
  ],
  "product_titles": {{
    "t_shirt": "Shopify SEO title for t-shirt (include keyword + brand)",
    "mug": "Shopify SEO title for mug listing",
    "tote_bag": "Shopify SEO title for tote bag listing"
  }},
  "listing_description": "2-sentence product description optimized for Shopify/SEO, benefit-focused",
  "tags": [
    "tag1", "tag2", "tag3", "tag4", "tag5",
    "tag6", "tag7", "tag8", "tag9", "tag10",
    "tag1", "tag2", "tag3", "tag4", "tag5",
    "tag6", "tag7", "tag8", "tag9", "tag10",
    "tag11", "tag12", "tag13"
  ]
}}

Tags must be Shopify/Etsy SEO terms: mix of theme keywords, product type, audience (motivational gift, gym shirt, etc.)"""

    return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=1400, smart=True)


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


def draw_gold_rule(draw, w: int, y: int, span_pct: float = 0.55, thickness: int = 6):
    """Draw a centered gold horizontal rule."""
    span = int(w * span_pct)
    x0 = (w - span) // 2
    draw.line([(x0, y), (x0 + span, y)], fill=BRAND_GOLD, width=thickness)


def draw_border_frame(draw, w: int, h: int, margin: int = 120, thickness: int = 4):
    """Draw a thin gold rectangular border inset from the edges."""
    m = margin
    draw.rectangle([m, m, w - m, h - m], outline=BRAND_GOLD, width=thickness)


def fit_font_to_width(text: str, draw, max_width: int,
                      start_size: int = 700, min_size: int = 120) -> tuple:
    """Return (font, actual_size) that fits text within max_width pixels."""
    size = start_size
    while size >= min_size:
        font = get_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font, size
        size -= 10
    return get_font(min_size), min_size


def layout_main_lines(main_text: str) -> list[str]:
    """
    Split a short motivational phrase into high-impact display lines.
    Strategy: one or two words per line for maximum visual weight.
    """
    words = main_text.upper().split()
    if len(words) == 1:
        return words
    if len(words) == 2:
        return words                     # one word each line
    if len(words) == 3:
        return [words[0], " ".join(words[1:])]   # 1 / 2
    if len(words) == 4:
        return [" ".join(words[:2]), " ".join(words[2:])]  # 2 / 2
    # 5+ words: pairs
    lines = []
    for i in range(0, len(words), 2):
        lines.append(" ".join(words[i:i + 2]))
    return lines


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
    """
    Render a high-impact motivational POD design.
    4500×4500 px (print-quality), solid black bg, massive white text, gold accents.
    """
    if not PILLOW_OK:
        print(f"  [SKIP] Pillow unavailable — skipping PNG generation")
        return

    main_text = concept.get("main_text", "RISE UP").upper()
    sub_text  = concept.get("sub_text",  "built different").upper()
    w, h = CANVAS_SIZE   # 4500 × 4500

    out_path_colored.parent.mkdir(parents=True, exist_ok=True)

    # ── COLORED (dark background) VERSION ────────────────────────────────────
    img  = Image.new("RGB", (w, h), BRAND_BG)
    draw = ImageDraw.Draw(img)

    # Thin gold border frame
    draw_border_frame(draw, w, h, margin=140, thickness=5)

    # Split phrase into display lines for maximum visual weight
    lines = layout_main_lines(main_text)

    # Find the largest font size where the widest line fits in 84% of canvas
    max_text_w = int(w * 0.84)
    widest = max(lines, key=len)
    main_font, font_size = fit_font_to_width(widest, draw, max_text_w,
                                              start_size=700, min_size=120)

    # Tight leading: 95% of font size so lines feel powerful, not airy
    line_h     = int(font_size * 0.95)
    total_text_h = len(lines) * line_h

    # Center text block — nudge up slightly to leave room for sub text
    text_block_y = (h - total_text_h) // 2 - int(font_size * 0.3)

    for i, line in enumerate(lines):
        bbox  = draw.textbbox((0, 0), line, font=main_font)
        text_w = bbox[2] - bbox[0]
        x = (w - text_w) // 2
        y = text_block_y + i * line_h
        draw.text((x, y), line, font=main_font, fill=BRAND_WHITE)

    # Gold rule below main text
    rule_y = text_block_y + total_text_h + int(font_size * 0.18)
    draw_gold_rule(draw, w, rule_y, span_pct=0.42, thickness=7)

    # Sub text — refined, gold, smaller
    sub_font_size = max(80, font_size // 6)
    sub_font = get_font_regular(sub_font_size)
    sub_bbox  = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_x = (w - (sub_bbox[2] - sub_bbox[0])) // 2
    sub_y = rule_y + 55
    draw.text((sub_x, sub_y), sub_text, font=sub_font, fill=BRAND_GOLD)

    # Brand mark — very subtle at bottom center
    brand_font = get_font_regular(60)
    brand_text = "RISE SUPPLY CO."
    bb = draw.textbbox((0, 0), brand_text, font=brand_font)
    draw.text(((w - (bb[2] - bb[0])) // 2, h - 220),
              brand_text, font=brand_font, fill=BRAND_GRAY)

    img.save(str(out_path_colored), "PNG", dpi=(300, 300))

    # ── TRANSPARENT VERSION (white text on clear bg — for light products) ────
    img_t  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_t = ImageDraw.Draw(img_t)

    # Border
    draw_border_frame(draw_t, w, h, margin=140, thickness=5)

    for i, line in enumerate(lines):
        bbox  = draw_t.textbbox((0, 0), line, font=main_font)
        text_w = bbox[2] - bbox[0]
        x = (w - text_w) // 2
        y = text_block_y + i * line_h
        draw_t.text((x, y), line, font=main_font, fill=(13, 13, 13, 255))

    draw_gold_rule(draw_t, w, rule_y, span_pct=0.42, thickness=7)

    sub_bb = draw_t.textbbox((0, 0), sub_text, font=sub_font)
    draw_t.text(((w - (sub_bb[2] - sub_bb[0])) // 2, sub_y),
                sub_text, font=sub_font, fill=(*BRAND_GOLD, 230))

    bb_t = draw_t.textbbox((0, 0), brand_text, font=brand_font)
    draw_t.text(((w - (bb_t[2] - bb_t[0])) // 2, h - 220),
                brand_text, font=brand_font, fill=(*BRAND_GRAY, 180))

    img_t.save(str(out_path_transparent), "PNG", dpi=(300, 300))
    print(f"  Saved: {out_path_colored.name} ({w}×{h} @ 300 DPI)")


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

    # Auto-publish to Shopify via Printify if API key is set
    published = []
    if os.environ.get("PRINTIFY_API_KEY"):
        print("\n  [Printify] API key found — auto-publishing to Shopify...")
        try:
            from agents.printify.publisher import publish_design_to_shopify
            for concept in concepts:
                colored_path = Path(concept["files"]["colored"])
                if colored_path.exists():
                    products = publish_design_to_shopify(concept, colored_path)
                    published.extend(products)
                    concept["shopify_products"] = products
        except Exception as e:
            print(f"  [Printify] Publish error: {e}")
            print("  [Printify] Designs saved locally — upload manually via redbubble_upload_guide.txt")
    else:
        print("\n  [Printify] PRINTIFY_API_KEY not set — skipping auto-publish.")
        print("  Add PRINTIFY_API_KEY to GitHub secrets to enable autonomous publishing.")

    # Re-save designs.json with Shopify product links
    save_json(designs_json_path, {"date": datestamp(), "designs": concepts, "published": published})

    if published:
        print(f"\n  [Printify] Published {len(published)} products to Shopify automatically!")
    print(f"\n[POD Agent] Done. Created {len(concepts)} designs in {out_dir}\n")

    return {
        "status": "success",
        "designs": len(concepts),
        "published_to_shopify": len(published),
        "outputs": [str(out_dir)],
    }


if __name__ == "__main__":
    run()
