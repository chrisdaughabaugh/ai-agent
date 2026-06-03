"""Stock Images Agent — generates AI image prompts, metadata, and submission-ready files for stock sites."""

import sys
import os
import json
import csv
import textwrap
from pathlib import Path
from datetime import datetime

# Allow imports from shared/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import slugify, save_text, save_json, datestamp

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise ImportError("Pillow is required: pip install Pillow")

AGENT_NAME = "stock_images"
REPO_ROOT = Path(__file__).parent.parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs" / "stock_images"

# High-demand commercial stock categories proven to sell
STOCK_CATEGORIES = [
    "business/office",
    "lifestyle",
    "food & drink",
    "technology",
    "nature & environment",
    "diversity & inclusion",
    "wellness & self-care",
    "remote work",
    "family & relationships",
    "education & learning",
    "travel & adventure",
    "health & fitness",
    "finance & money",
    "sustainability & eco",
    "celebrations & holidays",
]

# Shutterstock CSV column headers
SHUTTERSTOCK_HEADERS = [
    "Filename",
    "Description",
    "Keywords",
    "Categories",
    "Editorial",
    "Mature content",
]

# Adobe Stock CSV column headers
ADOBE_HEADERS = [
    "Filename",
    "Title",
    "Keywords",
    "Category",
    "Releases",
]

SUBMISSION_GUIDE = """STOCK IMAGE SUBMISSION GUIDE
============================
Generated: {date}
Batch: {batch_name}
Concepts: {concept_count}

OVERVIEW
--------
This batch contains {concept_count} AI image concepts with full metadata for
Shutterstock and Adobe Stock. Follow these steps to submit them:

STEP 1: GENERATE THE ACTUAL IMAGES
------------------------------------
Use the prompts in prompts.json with an AI image generator:

Option A — Midjourney (Recommended for quality):
  1. Open Discord and join Midjourney server (midjourney.com)
  2. Use the /imagine command with each prompt
  3. Choose "Upscale" on the best variation
  4. Download at full resolution
  5. Save as JPEG, minimum 4MP (e.g. 2400x1600 pixels)

Option B — DALL-E 3 (via ChatGPT Plus):
  1. Go to chat.openai.com
  2. Paste each prompt into the chat
  3. Download the generated image
  4. Upscale if needed using upscayl.org (free)

Option C — Stable Diffusion (Free, local):
  1. Install AUTOMATIC1111 or ComfyUI
  2. Use SDXL or Juggernaut XL model
  3. Set resolution to 1024x1024 minimum
  4. Upscale 2x with ESRGAN or similar

IMAGE QUALITY REQUIREMENTS
---------------------------
- Minimum: 4 megapixels (e.g., 2400x1600)
- Recommended: 8-25 megapixels
- Format: JPEG (quality 90+) or TIFF
- No watermarks, logos, or text overlays
- Sharp focus, proper exposure
- No AI artifacts (check edges, hands, text in image)

STEP 2: NAME YOUR FILES
------------------------
Rename each generated image to match the filename in the CSV files:
  concept_01.jpg, concept_02.jpg, ... concept_10.jpg

STEP 3: SUBMIT TO SHUTTERSTOCK
--------------------------------
  1. Go to: submit.shutterstock.com
  2. Click "Upload" and batch upload all images
  3. Once uploaded, click "Edit metadata"
  4. Click "Import CSV" and upload metadata_shutterstock.csv
  5. Review each image for auto-filled metadata
  6. Click "Submit for review"
  7. Review takes 1-3 business days

Shutterstock royalties: $0.25 - $2.85 per download (level-based)

STEP 4: SUBMIT TO ADOBE STOCK
-------------------------------
  1. Go to: contributor.stock.adobe.com
  2. Create contributor account if needed
  3. Click "Upload" and select all images
  4. In the dashboard, use "Bulk Edit" > "Import CSV"
  5. Upload metadata_adobe.csv
  6. Review and submit
  7. Review takes 2-5 business days

Adobe Stock royalties: 33% of sale price (~$0.33 - $3.30 per download)

STEP 5: ALSO CONSIDER THESE PLATFORMS
---------------------------------------
- Getty Images / iStock: gettyimages.com/contributor
  (Higher per-image rates, stricter acceptance)
- Dreamstime: dreamstime.com/sell-stock-photos
  (Good supplementary income, 25-50% royalties)
- Pond5: pond5.com/sell-stock-footage
  (Good for video clips too, 35-50% royalties)
- Freepik: freepik.com/sell-your-work
  (High volume, lower per-download but huge audience)

TIPS FOR ACCEPTANCE
--------------------
- Avoid recognizable faces without model releases
- Avoid trademarked logos or brands visible in image
- Avoid identifiable private property without release
- Keep metadata honest and accurate to image content
- Diverse, inclusive images have higher acceptance rates
- Business-relevant concepts sell best consistently

TRACKING EARNINGS
------------------
- Check your contributor dashboards weekly
- Most sites pay monthly via PayPal or bank transfer
- Shutterstock: Pay threshold $35
- Adobe Stock: Pay threshold $25
- Expect 2-6 months before first meaningful earnings
- A portfolio of 500+ images earns consistently

Good luck with your submissions!
"""


# ---------------------------------------------------------------------------
# Concept generation via Claude
# ---------------------------------------------------------------------------

def _generate_batch_concepts(categories: list, batch_size: int = 10) -> list:
    """Use Claude to generate a batch of high-value stock image concepts."""
    category_str = ", ".join(categories[:batch_size])
    prompt = f"""You are a professional stock photography director who knows exactly what sells on Shutterstock and Adobe Stock.

Generate {batch_size} high-demand commercial stock image concepts. Use these categories as inspiration: {category_str}

For each concept, return a JSON array. Each object must have exactly these fields:
{{
  "concept_id": "concept_01",  (concept_01 through concept_10)
  "category": "the stock category",
  "content_type": "photo",  (photo, illustration, or vector)
  "subject": "Brief 5-word subject description",
  "image_prompt": "Detailed 60-100 word prompt for AI image generation. Include: lighting style, composition, color palette, mood, specific details, camera angle, subject description. Written for Midjourney/DALL-E.",
  "title": "Stock image title, 5-10 words, factual and descriptive",
  "description": "75-100 word factual description of the image content for stock sites. No subjective language.",
  "keywords": ["keyword1", "keyword2", ...],  (exactly 20 highly relevant keywords)
  "shutterstock_category_1": "first Shutterstock category",
  "shutterstock_category_2": "second Shutterstock category",
  "adobe_category": "Adobe Stock category number",
  "has_people": true or false,
  "requires_model_release": true or false,
  "requires_property_release": false,
  "orientation": "horizontal",  (horizontal, vertical, or square)
  "color_palette": "brief color description"
}}

Adobe Stock category numbers: 1=Animals, 2=Buildings/Landmarks, 3=Business/Finance, 4=Drinks, 5=Environment/Conservation, 6=States of Mind, 7=Food, 8=Graphic Resources, 9=Hobbies/Leisure, 10=Industry, 11=Landscapes, 12=Lifestyle, 13=People, 14=Plants/Flowers, 15=Culture/Religion, 16=Science, 17=Social Issues, 18=Sports, 19=Technology, 20=Transport/Vehicle, 21=Travel

Focus on concepts that:
- Have clear commercial applications (can be used in ads, websites, presentations)
- Feature diverse subjects and settings
- Are achievable with AI image generators
- Are in high demand for businesses and marketers
- Avoid overly specific or niche scenarios

Return ONLY a valid JSON array, no other text."""

    return generate_json(prompt, smart=True, max_tokens=4000)


def _select_categories_for_batch(batch_num: int = 0) -> list:
    """Pick a diverse spread of categories for this batch."""
    import random
    # Rotate through categories, ensuring variety
    start = (batch_num * 5) % len(STOCK_CATEGORIES)
    pool = STOCK_CATEGORIES[start:] + STOCK_CATEGORIES[:start]
    # Take 10 with some randomness
    selected = pool[:8] + random.sample(STOCK_CATEGORIES, 2)
    return list(dict.fromkeys(selected))[:10]


# ---------------------------------------------------------------------------
# Placeholder image creation with Pillow
# ---------------------------------------------------------------------------

def _make_placeholder_image(concept: dict, out_path: Path):
    """Create a placeholder PNG that shows the prompt text and concept info."""
    width, height = 1200, 800
    # Pick background color based on category
    bg_colors = {
        "business/office": (245, 247, 250),
        "lifestyle": (252, 248, 243),
        "food & drink": (255, 250, 240),
        "technology": (240, 245, 255),
        "nature & environment": (240, 252, 244),
        "diversity & inclusion": (252, 240, 255),
        "wellness & self-care": (240, 255, 252),
        "remote work": (245, 245, 255),
        "family & relationships": (255, 245, 245),
        "education & learning": (255, 252, 235),
        "travel & adventure": (235, 248, 255),
        "health & fitness": (240, 255, 245),
        "finance & money": (245, 255, 240),
        "sustainability & eco": (240, 252, 240),
        "celebrations & holidays": (255, 245, 250),
    }
    cat = concept.get("category", "").lower()
    bg_color = bg_colors.get(cat, (248, 248, 248))

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Accent color bar at top
    accent_colors = {
        "business/office": (41, 98, 255),
        "lifestyle": (255, 107, 107),
        "food & drink": (255, 165, 0),
        "technology": (0, 188, 212),
        "nature & environment": (76, 175, 80),
        "diversity & inclusion": (156, 39, 176),
        "wellness & self-care": (0, 188, 188),
        "remote work": (63, 81, 181),
        "family & relationships": (233, 30, 99),
        "education & learning": (255, 152, 0),
        "travel & adventure": (3, 169, 244),
        "health & fitness": (76, 175, 80),
        "finance & money": (0, 150, 136),
        "sustainability & eco": (56, 142, 60),
        "celebrations & holidays": (233, 30, 99),
    }
    accent = accent_colors.get(cat, (41, 98, 255))
    draw.rectangle([0, 0, width, 8], fill=accent)
    draw.rectangle([0, height - 8, width, height], fill=accent)

    # Watermark diagonal text (subtle)
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except (IOError, OSError):
        font_small = ImageFont.load_default()
        font_medium = font_small
        font_large = font_small
        font_tiny = font_small

    # Header band
    draw.rectangle([0, 8, width, 70], fill=(*accent, 220))

    # Concept ID + category
    cid = concept.get("concept_id", "concept_01").upper()
    cat_display = concept.get("category", "Stock Image").title()
    draw.text((20, 18), f"[PLACEHOLDER] {cid} — {cat_display}", font=font_medium, fill=(255, 255, 255))
    draw.text((20, 44), f"Content type: {concept.get('content_type', 'photo').upper()}  |  Orientation: {concept.get('orientation', 'horizontal').upper()}", font=font_small, fill=(220, 230, 255))

    # Title
    title = concept.get("title", "Stock Image Concept")
    draw.text((20, 90), title, font=font_large, fill=(30, 30, 60))

    # Divider
    draw.line([(20, 130), (width - 20, 130)], fill=(*accent[:3], 80), width=1)

    # Prompt section label
    draw.text((20, 142), "AI IMAGE PROMPT:", font=font_small, fill=(*accent[:3],))

    # Wrap and render prompt text
    prompt_text = concept.get("image_prompt", "")
    wrapped_lines = []
    words = prompt_text.split()
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        # Approximate 95 chars per line for font size 14
        if len(test) > 95:
            wrapped_lines.append(line)
            line = word
        else:
            line = test
    if line:
        wrapped_lines.append(line)

    y_pos = 162
    for ln in wrapped_lines[:8]:
        draw.text((20, y_pos), ln, font=font_small, fill=(50, 50, 80))
        y_pos += 18
        if y_pos > 310:
            draw.text((20, y_pos), "...", font=font_small, fill=(100, 100, 120))
            break

    # Divider
    draw.line([(20, 330), (width - 20, 330)], fill=(*accent[:3], 80), width=1)

    # Keywords preview
    draw.text((20, 342), "TOP KEYWORDS:", font=font_small, fill=(*accent[:3],))
    kws = concept.get("keywords", [])[:10]
    kw_text = "  ·  ".join(kws)
    # Wrap keywords
    if len(kw_text) > 100:
        kw_text = kw_text[:97] + "..."
    draw.text((20, 362), kw_text, font=font_tiny, fill=(60, 60, 100))

    # Color palette
    draw.text((20, 390), f"Color palette: {concept.get('color_palette', 'N/A')}", font=font_tiny, fill=(80, 80, 100))

    # Bottom metadata bar
    draw.rectangle([0, height - 90, width, height - 8], fill=(245, 245, 252))
    draw.line([(0, height - 90), (width, height - 90)], fill=(*accent[:3], 60), width=1)

    meta_left = f"People: {'Yes' if concept.get('has_people') else 'No'}  |  Model release: {'Required' if concept.get('requires_model_release') else 'Not required'}"
    meta_right = f"Shutterstock: {concept.get('shutterstock_category_1', '')}  |  Adobe: Category {concept.get('adobe_category', '')}"

    draw.text((20, height - 78), meta_left, font=font_tiny, fill=(80, 80, 120))
    draw.text((20, height - 60), meta_right, font=font_tiny, fill=(80, 80, 120))

    subject = concept.get("subject", "")
    draw.text((20, height - 42), f"Subject: {subject}", font=font_small, fill=(40, 40, 80))

    # Watermark text (diagonal, very subtle)
    watermark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    wm_draw = ImageDraw.Draw(watermark_layer)
    try:
        wm_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except (IOError, OSError):
        wm_font = ImageFont.load_default()
    wm_draw.text((width // 2 - 120, height // 2 - 20), "PLACEHOLDER", font=wm_font, fill=(0, 0, 0, 18))
    img = Image.alpha_composite(img.convert("RGBA"), watermark_layer).convert("RGB")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG", optimize=True)


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

def _write_shutterstock_csv(concepts: list, out_path: Path):
    """Write Shutterstock batch upload CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHUTTERSTOCK_HEADERS)
        writer.writeheader()
        for c in concepts:
            filename = f"{c['concept_id']}.jpg"
            keywords_str = ", ".join(c.get("keywords", [])[:50])  # Shutterstock max 50
            cats = []
            if c.get("shutterstock_category_1"):
                cats.append(c["shutterstock_category_1"])
            if c.get("shutterstock_category_2"):
                cats.append(c["shutterstock_category_2"])
            writer.writerow({
                "Filename": filename,
                "Description": c.get("description", "")[:200],
                "Keywords": keywords_str,
                "Categories": ", ".join(cats),
                "Editorial": "no",
                "Mature content": "no",
            })


def _write_adobe_csv(concepts: list, out_path: Path):
    """Write Adobe Stock batch upload CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ADOBE_HEADERS)
        writer.writeheader()
        for c in concepts:
            filename = f"{c['concept_id']}.jpg"
            # Adobe allows up to 50 keywords
            keywords_str = ", ".join(c.get("keywords", [])[:50])
            writer.writerow({
                "Filename": filename,
                "Title": c.get("title", "")[:200],
                "Keywords": keywords_str,
                "Category": str(c.get("adobe_category", "12")),
                "Releases": "no",
            })


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(config: dict = None) -> dict:
    """Run the Stock Images agent end-to-end."""
    config = config or {}

    print(f"[StockImages Agent] Starting run at {datetime.now().strftime('%H:%M:%S')}")

    batch_num = config.get("batch_num", 0)
    batch_size = config.get("batch_size", 10)

    # 1. Select categories for this batch
    print("[StockImages Agent] Selecting high-demand categories...")
    categories = _select_categories_for_batch(batch_num)
    print(f"[StockImages Agent] Categories: {', '.join(categories[:5])}...")

    # 2. Generate 10 image concepts via Claude
    print(f"[StockImages Agent] Generating {batch_size} image concepts with Claude...")
    try:
        concepts = _generate_batch_concepts(categories, batch_size)
        if not isinstance(concepts, list):
            raise ValueError("Expected a list of concepts")
        # Normalize concept_ids in case Claude numbered them differently
        for i, c in enumerate(concepts):
            c["concept_id"] = f"concept_{i + 1:02d}"
        print(f"[StockImages Agent] Generated {len(concepts)} concepts")
    except Exception as e:
        print(f"[StockImages Agent] Error generating concepts: {e}")
        raise

    # 3. Set up output directory
    batch_name = f"batch-{datestamp()}"
    out_dir = OUTPUTS_DIR / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[StockImages Agent] Output directory: {out_dir}")

    # 4. Save prompts.json
    prompts_path = out_dir / "prompts.json"
    save_json(prompts_path, {
        "batch": batch_name,
        "generated_date": datestamp(),
        "total_concepts": len(concepts),
        "categories_used": categories,
        "concepts": concepts,
    })
    print(f"[StockImages Agent] Saved prompts.json")

    # 5. Write Shutterstock CSV
    ss_csv_path = out_dir / "metadata_shutterstock.csv"
    try:
        _write_shutterstock_csv(concepts, ss_csv_path)
        print(f"[StockImages Agent] Saved metadata_shutterstock.csv")
    except Exception as e:
        print(f"[StockImages Agent] Shutterstock CSV error: {e}")
        ss_csv_path = None

    # 6. Write Adobe Stock CSV
    adobe_csv_path = out_dir / "metadata_adobe.csv"
    try:
        _write_adobe_csv(concepts, adobe_csv_path)
        print(f"[StockImages Agent] Saved metadata_adobe.csv")
    except Exception as e:
        print(f"[StockImages Agent] Adobe CSV error: {e}")
        adobe_csv_path = None

    # 7. Generate placeholder images
    placeholder_paths = []
    for concept in concepts:
        cid = concept.get("concept_id", f"concept_{len(placeholder_paths)+1:02d}")
        img_path = out_dir / f"{cid}.png"
        try:
            _make_placeholder_image(concept, img_path)
            placeholder_paths.append(str(img_path))
        except Exception as e:
            print(f"[StockImages Agent] Placeholder error for {cid}: {e}")

    print(f"[StockImages Agent] Created {len(placeholder_paths)} placeholder images")

    # 8. Write submission guide
    guide_path = out_dir / "submission_guide.txt"
    guide_content = SUBMISSION_GUIDE.format(
        date=datestamp(),
        batch_name=batch_name,
        concept_count=len(concepts),
    )
    save_text(guide_path, guide_content)
    print(f"[StockImages Agent] Saved submission_guide.txt")

    # 9. Log output
    titles = [c.get("title", "") for c in concepts[:3]]
    log_output(
        AGENT_NAME,
        f"Stock Image Batch — {batch_name}",
        str(out_dir),
        f"{len(concepts)} concepts | Examples: {'; '.join(titles)}",
    )

    result = {
        "status": "success",
        "batch": batch_name,
        "output_dir": str(out_dir),
        "concept_count": len(concepts),
        "placeholder_images": len(placeholder_paths),
        "files": {
            "prompts": str(prompts_path),
            "shutterstock_csv": str(ss_csv_path) if ss_csv_path else None,
            "adobe_csv": str(adobe_csv_path) if adobe_csv_path else None,
            "submission_guide": str(guide_path),
        },
        "concepts_preview": [
            {
                "id": c.get("concept_id"),
                "title": c.get("title"),
                "category": c.get("category"),
            }
            for c in concepts[:5]
        ],
    }

    print(f"[StockImages Agent] Done! Output: {out_dir}")
    return result


if __name__ == "__main__":
    result = run()
    print("\n=== Stock Images Agent Result ===")
    print(json.dumps(result, indent=2))
