"""Amazon KDP Books Agent — researches niches, generates manuscripts, builds print-ready PDFs."""

import sys
import os
import json
import re
import textwrap
from pathlib import Path
from datetime import datetime

# Allow imports from shared/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import (
    slugify, fetch_page, save_text, save_json, datestamp
)

try:
    from fpdf import FPDF
except ImportError:
    from fpdf2 import FPDF

AGENT_NAME = "kdp"
REPO_ROOT = Path(__file__).parent.parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs" / "books"
DATA_FILE = REPO_ROOT / "data" / "kdp_state.json"

FALLBACK_NICHES = [
    "gratitude journal",
    "habit tracker",
    "self-improvement workbook",
    "meal planner",
    "budget planner",
    "children's activity book",
    "affirmation journal",
    "mindfulness journal",
    "fitness tracker",
    "pregnancy journal",
    "travel journal",
    "anxiety relief workbook",
    "goal setting planner",
    "reading journal",
    "garden planner",
]

AMAZON_BESTSELLER_URLS = [
    "https://www.amazon.com/Best-Sellers-Books/zgbs/books/",
    "https://www.amazon.com/gp/bestsellers/books/",
]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"done_niches": [], "runs": []}


def _save_state(state: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Niche research
# ---------------------------------------------------------------------------

def _scrape_amazon_niches() -> list:
    """Attempt to pull niche signals from Amazon bestseller pages."""
    found = []
    for url in AMAZON_BESTSELLER_URLS:
        html = fetch_page(url, timeout=12)
        if not html:
            continue
        # Extract product titles from common Amazon bestseller HTML patterns
        patterns = [
            r'class="[^"]*zg-item-title[^"]*"[^>]*>\s*<[^>]+>([^<]{10,120})<',
            r'class="[^"]*p13n-sc-truncate[^"]*"[^>]*>([^<]{10,120})<',
            r'"asin-metadata".*?"title"\s*:\s*"([^"]{10,120})"',
            r'<span[^>]+class="[^"]*a-size-small[^"]*"[^>]*>([^<]{10,80})</span>',
        ]
        for pat in patterns:
            matches = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
            for m in matches:
                title = m.strip()
                if any(kw in title.lower() for kw in
                       ["journal", "planner", "workbook", "tracker",
                        "notebook", "diary", "activity", "coloring"]):
                    found.append(title)
    return list(dict.fromkeys(found))[:20]  # deduplicate, cap at 20


def _pick_niche(state: dict, scraped: list) -> str:
    """Select the best niche not recently used."""
    done = set(state.get("done_niches", []))

    # Build candidate list: scraped hits first, then fallbacks
    candidates = []
    for title in scraped:
        # Normalize scraped title to a short niche phrase
        niche = title.lower()[:60].strip()
        if niche not in done:
            candidates.append(niche)

    for niche in FALLBACK_NICHES:
        if niche not in done and niche not in candidates:
            candidates.append(niche)

    if not candidates:
        # All niches used — reset and start over
        state["done_niches"] = []
        _save_state(state)
        candidates = list(FALLBACK_NICHES)

    chosen = candidates[0]
    state["done_niches"].append(chosen)
    _save_state(state)
    return chosen


# ---------------------------------------------------------------------------
# Claude content generation
# ---------------------------------------------------------------------------

def _generate_book_meta(niche: str) -> dict:
    """Generate SEO-optimized title, subtitle, description, and keywords."""
    prompt = f"""You are an expert Amazon KDP publisher. Generate a complete book listing for a low-content book in the niche: "{niche}".

Return ONLY valid JSON with these exact fields:
{{
  "title": "Main book title (4-8 words, SEO optimized for Amazon)",
  "subtitle": "Subtitle that adds value and keywords (10-15 words)",
  "description": "Back cover / Amazon listing description (200 words, keyword-rich, compelling, includes benefits)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6", "keyword7"],
  "primary_category": "Books > Self-Help > ...",
  "secondary_category": "Books > Health, Fitness & Dieting > ...",
  "audience": "Brief description of target reader",
  "chapter_themes": ["theme1", "theme2", "theme3", "theme4", "theme5", "theme6", "theme7"]
}}

Keywords must be Amazon search terms people actually type. The title should beat competitors in search rankings."""
    return generate_json(prompt, smart=True, max_tokens=1500)


def _generate_chapter(niche: str, theme: str, chapter_num: int, title: str) -> str:
    """Generate a single chapter of 400-600 words."""
    prompt = f"""Write Chapter {chapter_num} of a {niche} book titled "{title}".
Chapter theme: {theme}

Write 450-550 words of genuine, helpful content. Include:
- An engaging chapter opening paragraph
- 3-4 main points or sections with practical advice
- Actionable tips the reader can use immediately
- A closing paragraph that transitions to the next chapter

Write in second person ("you"). Be warm, encouraging, and practical. No generic filler — real advice.
Output only the chapter body text, no chapter heading needed."""
    return generate(prompt, smart=True, max_tokens=900)


def _generate_introduction(niche: str, title: str, audience: str) -> str:
    prompt = f"""Write a compelling introduction for a {niche} book titled "{title}".
Target audience: {audience}

Write 300-400 words that:
- Hook the reader immediately with a relatable scenario or bold statement
- Explain exactly what this book will help them achieve
- Briefly describe what each section covers
- End with an encouraging call to action to begin

Output only the introduction text, no heading needed."""
    return generate(prompt, smart=True, max_tokens=700)


def _generate_manuscript(meta: dict, niche: str) -> dict:
    """Generate full manuscript content."""
    title = meta["title"]
    audience = meta.get("audience", "general readers")
    themes = meta.get("chapter_themes", [
        "Getting Started", "Building Foundations", "Core Practice",
        "Overcoming Challenges", "Advanced Techniques",
        "Maintaining Progress", "Living the Transformation"
    ])

    print(f"  Generating introduction...")
    introduction = _generate_introduction(niche, title, audience)

    chapters = []
    for i, theme in enumerate(themes[:7], start=1):
        print(f"  Generating chapter {i}: {theme}...")
        content = _generate_chapter(niche, theme, i, title)
        chapters.append({"number": i, "theme": theme, "content": content})

    return {"introduction": introduction, "chapters": chapters}


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

class KDPBook(FPDF):
    """Custom FPDF subclass for KDP 6x9 formatting."""

    def __init__(self, title: str, subtitle: str):
        # 6x9 inches in mm: 152.4 x 228.6
        super().__init__(unit="mm", format=(152.4, 228.6))
        self.book_title = title
        self.book_subtitle = subtitle
        self.set_margins(19.05, 19.05, 19.05)  # 3/4 inch margins
        self.set_auto_page_break(auto=True, margin=19.05)

    def header(self):
        # Running header on non-title pages
        if self.page_no() > 2:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 8, self.book_title[:50], align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)

    def footer(self):
        if self.page_no() > 2:
            self.set_y(-15)
            self.set_font("Helvetica", "", 9)
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, str(self.page_no() - 2), align="C")
            self.set_text_color(0, 0, 0)

    def title_page(self):
        self.add_page()
        self.set_y(45)
        # Decorative line
        self.set_draw_color(180, 140, 60)
        self.set_line_width(0.8)
        self.line(25, self.get_y(), 127, self.get_y())
        self.ln(8)
        # Title
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 11, self.book_title, align="C")
        self.ln(5)
        # Decorative line
        self.set_draw_color(180, 140, 60)
        self.line(25, self.get_y(), 127, self.get_y())
        self.ln(10)
        # Subtitle
        self.set_font("Helvetica", "I", 13)
        self.set_text_color(80, 80, 80)
        self.multi_cell(0, 8, self.book_subtitle, align="C")
        self.ln(30)
        # Bottom decoration
        self.set_y(170)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(140, 140, 140)
        self.cell(0, 6, "Published via Amazon KDP", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 6, str(datetime.now().year), align="C")

    def copyright_page(self):
        self.add_page()
        self.set_y(160)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 100, 100)
        year = datetime.now().year
        lines = [
            f"Copyright © {year} All rights reserved.",
            "",
            "No part of this publication may be reproduced, distributed, or",
            "transmitted in any form or by any means without prior written permission.",
            "",
            "Printed in the United States of America",
            "First Edition",
        ]
        for line in lines:
            self.cell(0, 5, line, align="C", new_x="LMARGIN", new_y="NEXT")

    def chapter_heading(self, number: int, theme: str):
        self.add_page()
        self.ln(10)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(140, 100, 40)
        self.cell(0, 8, f"CHAPTER {number}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self.set_font("Helvetica", "B", 17)
        self.set_text_color(25, 25, 25)
        self.multi_cell(0, 10, theme, align="C")
        self.ln(4)
        # Underline
        self.set_draw_color(180, 140, 60)
        self.set_line_width(0.5)
        self.line(35, self.get_y(), 117, self.get_y())
        self.ln(10)
        self.set_text_color(0, 0, 0)

    def section_heading(self, text: str):
        self.ln(4)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 7, text)
        self.ln(1)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(0, 0, 0)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(20, 20, 20)
        # Split into paragraphs
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        for para in paragraphs:
            # Detect if it looks like a heading (short, ends with colon or all caps fraction)
            if len(para) < 60 and (para.endswith(":") or para.isupper()):
                self.section_heading(para)
            else:
                self.multi_cell(0, 6, para, align="J")
                self.ln(3)

    def intro_heading(self):
        self.add_page()
        self.ln(10)
        self.set_font("Helvetica", "B", 17)
        self.set_text_color(25, 25, 25)
        self.cell(0, 10, "Introduction", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_draw_color(180, 140, 60)
        self.set_line_width(0.5)
        self.line(35, self.get_y(), 117, self.get_y())
        self.ln(10)
        self.set_text_color(0, 0, 0)


def _build_pdf(meta: dict, manuscript: dict, out_path: Path):
    """Assemble a complete KDP-ready PDF."""
    pdf = KDPBook(meta["title"], meta["subtitle"])

    # Front matter
    pdf.title_page()
    pdf.copyright_page()

    # Introduction
    pdf.intro_heading()
    pdf.body_text(manuscript["introduction"])

    # Chapters
    for ch in manuscript["chapters"]:
        pdf.chapter_heading(ch["number"], ch["theme"])
        pdf.body_text(ch["content"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


# ---------------------------------------------------------------------------
# Upload guide
# ---------------------------------------------------------------------------

UPLOAD_GUIDE_TEMPLATE = """AMAZON KDP UPLOAD GUIDE
=======================
Book: {title}
Generated: {date}

STEP-BY-STEP UPLOAD INSTRUCTIONS
----------------------------------

1. LOG IN TO KDP
   Go to: https://kdp.amazon.com
   Sign in with your Amazon account (or create one free).

2. CREATE A NEW TITLE
   Click "Create" > "Paperback"

3. BOOK DETAILS (Paperback Details tab)
   - Language: English
   - Book Title: {title}
   - Subtitle: {subtitle}
   - Primary Author: [Your Name or Pen Name]
   - Description: [Paste from metadata.json "description" field]
   - Publishing Rights: I own the copyright
   - Keywords (7 max): {keywords_str}
   - Categories: {primary_category} / {secondary_category}
   - Age & Grade Range: Leave blank unless children's book

4. BOOK CONTENT (Paperback Content tab)
   - ISBN: Get a Free KDP ISBN
   - Publication Date: Leave blank (auto-filled)
   - Print Options:
     * Interior & paper type: Black & White, White paper
     * Trim size: 6 x 9 in
     * Bleed settings: No Bleed
     * Cover finish: Matte (recommended for journals/planners)
   - Upload Manuscript: Upload manuscript.pdf from this folder
   - Book Cover: Use KDP Cover Creator OR upload a custom cover
     (Recommended: Create a professional cover on Canva.com using the 6x9 template)

5. KDP COVER CREATOR TIPS
   - Choose a simple, clean template
   - Use your title and subtitle exactly as shown above
   - Pick colors that match the book's mood/niche
   - Add a tagline from the description

6. PAPERBACK RIGHTS & PRICING (Pricing tab)
   - Territories: All territories
   - Primary marketplace: Amazon.com
   - Pricing:
     * Recommended retail price: $8.99 - $12.99
     * KDP royalty: 60% after printing costs
     * Printing cost for 6x9 ~{page_count} pages: ~$3.22
     * Suggested list price: $9.99 (nets ~$2.77 royalty per sale)
   - Expanded Distribution: Enable for extra reach

7. PUBLISH
   - Click "Publish Your Paperback Book"
   - Review takes 24-72 hours
   - Once approved, your book goes live on Amazon

ALSO CONSIDER: KINDLE EBOOK VERSION
-------------------------------------
- Create a Kindle version (KDP > Create > eBook)
- Price at $2.99 - $4.99 for the eBook
- Enroll in KDP Select for 90 days to access Kindle Unlimited readers
- Kindle Unlimited pays per page read (~$0.004/page)

MARKETING TIPS
--------------
- Run a free promotion in KDP Select during your first week
- Ask friends/family for honest reviews
- Use the 7 keywords in your Amazon Ads campaigns
- Create a simple social media post showing the book cover

TRACKING YOUR SALES
--------------------
- Check KDP Reports dashboard daily
- Sales appear with 24-48 hour delay
- Payments issued monthly (60 days after end of month)

Good luck with your launch!
"""


def _write_upload_guide(meta: dict, page_count: int, out_path: Path):
    keywords_str = ", ".join(meta.get("keywords", []))
    content = UPLOAD_GUIDE_TEMPLATE.format(
        title=meta["title"],
        subtitle=meta["subtitle"],
        date=datestamp(),
        keywords_str=keywords_str,
        primary_category=meta.get("primary_category", "Books > Self-Help"),
        secondary_category=meta.get("secondary_category", "Books > Health, Fitness & Dieting"),
        page_count=page_count,
    )
    save_text(out_path, content)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(config: dict = None) -> dict:
    """Run the KDP Books agent end-to-end."""
    config = config or {}

    print(f"[KDP Agent] Starting run at {datetime.now().strftime('%H:%M:%S')}")

    # 1. Research niches
    print("[KDP Agent] Researching Amazon bestseller niches...")
    scraped = _scrape_amazon_niches()
    print(f"[KDP Agent] Scraped {len(scraped)} niche signals from Amazon")
    if not scraped:
        print("[KDP Agent] Falling back to curated niche list")

    # 2. Pick niche
    state = _load_state()
    chosen_niche = config.get("niche") or _pick_niche(state, scraped)
    print(f"[KDP Agent] Selected niche: {chosen_niche}")

    # 3. Generate book metadata
    print("[KDP Agent] Generating book title, description, keywords...")
    meta = _generate_book_meta(chosen_niche)
    print(f"[KDP Agent] Title: {meta['title']}")
    print(f"[KDP Agent] Subtitle: {meta['subtitle']}")

    # 4. Generate manuscript content
    print("[KDP Agent] Generating manuscript content (this takes a moment)...")
    manuscript = _generate_manuscript(meta, chosen_niche)

    # 5. Set up output directory
    slug = slugify(meta["title"])
    date_slug = f"{datestamp()}-{slug}"
    out_dir = OUTPUTS_DIR / date_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # 6. Build PDF
    print("[KDP Agent] Building print-ready PDF...")
    pdf_path = out_dir / "manuscript.pdf"
    try:
        _build_pdf(meta, manuscript, pdf_path)
        print(f"[KDP Agent] PDF saved: {pdf_path}")
    except Exception as e:
        print(f"[KDP Agent] PDF build error: {e}")
        # Save manuscript as text fallback
        txt_path = out_dir / "manuscript.txt"
        parts = [f"{meta['title']}\n{meta['subtitle']}\n\n"]
        parts.append(f"INTRODUCTION\n\n{manuscript['introduction']}\n\n")
        for ch in manuscript["chapters"]:
            parts.append(f"CHAPTER {ch['number']}: {ch['theme']}\n\n{ch['content']}\n\n")
        save_text(txt_path, "".join(parts))
        pdf_path = txt_path

    # 7. Save metadata JSON
    meta_path = out_dir / "metadata.json"
    full_meta = {
        **meta,
        "niche": chosen_niche,
        "generated_date": datestamp(),
        "output_dir": str(out_dir),
        "manuscript_path": str(pdf_path),
        "chapter_count": len(manuscript["chapters"]),
        "estimated_page_count": 60,
    }
    save_json(meta_path, full_meta)

    # 8. Write upload guide
    guide_path = out_dir / "kdp_upload_guide.txt"
    _write_upload_guide(meta, 60, guide_path)

    # 9. Log output
    log_output(
        AGENT_NAME,
        meta["title"],
        str(out_dir),
        f"Niche: {chosen_niche} | Keywords: {', '.join(meta.get('keywords', [])[:3])}",
    )

    # 10. Update run history
    state.setdefault("runs", []).append({
        "date": datestamp(),
        "niche": chosen_niche,
        "title": meta["title"],
        "output_dir": str(out_dir),
    })
    _save_state(state)

    result = {
        "status": "success",
        "niche": chosen_niche,
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "output_dir": str(out_dir),
        "files": {
            "manuscript": str(pdf_path),
            "metadata": str(meta_path),
            "upload_guide": str(guide_path),
        },
        "keywords": meta.get("keywords", []),
        "chapters": len(manuscript["chapters"]),
    }

    print(f"[KDP Agent] Done! Output: {out_dir}")
    return result


if __name__ == "__main__":
    result = run()
    print("\n=== KDP Agent Result ===")
    print(json.dumps(result, indent=2))
