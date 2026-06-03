"""
Builds professional-looking PDF ebooks from generated product content.
Uses fpdf2 — no external dependencies, works offline.
"""

from pathlib import Path
from typing import Dict
from fpdf import FPDF
import os


PRODUCTS_DIR = Path(__file__).parent.parent / "products"
PRODUCTS_DIR.mkdir(exist_ok=True)

# Color palette: deep navy + gold accent + clean white
COLOR_BG = (15, 30, 60)        # Deep navy
COLOR_ACCENT = (212, 175, 55)  # Gold
COLOR_TEXT = (30, 30, 40)      # Near black
COLOR_LIGHT = (245, 245, 248)  # Off-white
COLOR_MID = (100, 110, 130)    # Muted gray


class ProductPDF(FPDF):
    def __init__(self, product: Dict):
        super().__init__()
        self.product = product
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(20, 20, 20)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*COLOR_MID)
            self.cell(0, 8, self.product["title"], align="L")
            self.ln(0.5)
            self.set_draw_color(*COLOR_ACCENT)
            self.set_line_width(0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(4)

    def footer(self):
        if self.page_no() > 1:
            self.set_y(-15)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*COLOR_MID)
            self.cell(0, 8, f"Page {self.page_no() - 1}", align="C")

    def add_cover(self):
        self.add_page()

        # Background
        self.set_fill_color(*COLOR_BG)
        self.rect(0, 0, self.w, self.h, "F")

        # Accent bar
        self.set_fill_color(*COLOR_ACCENT)
        self.rect(0, self.h * 0.52, self.w, 4, "F")

        # Niche tag
        self.set_y(30)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*COLOR_ACCENT)
        niche_text = self.product.get("niche", "").upper()
        self.cell(0, 8, niche_text, align="C")

        # Main title
        self.set_y(52)
        self.set_font("Helvetica", "B", 26)
        self.set_text_color(255, 255, 255)
        title = self.product["title"]
        self.multi_cell(0, 12, title, align="C")

        # Subtitle
        self.ln(6)
        self.set_font("Helvetica", "", 13)
        self.set_text_color(200, 210, 230)
        subtitle = self.product.get("subtitle", "")
        self.multi_cell(0, 7, subtitle, align="C")

        # Tagline block
        self.set_y(self.h * 0.58)
        self.set_font("Helvetica", "I", 11)
        self.set_text_color(*COLOR_ACCENT)
        tagline = self.product.get("tagline", "")
        if tagline:
            self.multi_cell(0, 7, f'"{tagline}"', align="C")

        # Author
        author = os.environ.get("AUTHOR_NAME", "Digital Essentials")
        self.set_y(self.h - 40)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(180, 190, 210)
        self.cell(0, 8, f"by {author}", align="C")

    def add_toc(self, chapters):
        self.add_page()
        self.set_fill_color(*COLOR_LIGHT)
        self.rect(0, 0, self.w, self.h, "F")

        self.set_y(25)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*COLOR_BG)
        self.cell(0, 12, "Table of Contents", align="L")

        self.set_draw_color(*COLOR_ACCENT)
        self.set_line_width(1.5)
        self.line(self.l_margin, self.get_y() + 2, self.l_margin + 50, self.get_y() + 2)
        self.ln(16)

        for i, ch in enumerate(chapters, 1):
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(*COLOR_BG)
            self.cell(8, 8, f"{i}.", align="L")
            self.set_font("Helvetica", "", 11)
            self.multi_cell(0, 8, ch["title"])
            self.ln(2)

        # Quick wins section in TOC
        self.ln(4)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*COLOR_MID)
        self.cell(0, 8, "Bonus: Quick Wins Checklist")
        self.ln(8)
        self.cell(0, 8, "Resources & Next Steps")

    def add_chapter(self, number: int, chapter: Dict):
        self.add_page()

        # Chapter number accent
        self.set_y(20)
        self.set_font("Helvetica", "B", 40)
        self.set_text_color(*COLOR_ACCENT)
        self.set_fill_color(*COLOR_LIGHT)
        self.rect(0, 0, self.w, self.h, "F")
        self.cell(20, 16, str(number), align="L")

        # Chapter title
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*COLOR_BG)
        self.set_x(self.l_margin + 22)
        self.set_y(20)
        self.multi_cell(0, 9, chapter["title"])

        # Divider
        self.ln(2)
        self.set_draw_color(*COLOR_ACCENT)
        self.set_line_width(1.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(8)

        # Body content
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*COLOR_TEXT)

        content = chapter["content"]
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        for para in paragraphs:
            self.multi_cell(0, 6.5, para)
            self.ln(4)

    def add_quick_wins(self, quick_wins):
        self.add_page()
        self.set_fill_color(*COLOR_BG)
        self.rect(0, 0, self.w, self.h, "F")

        self.set_y(30)
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*COLOR_ACCENT)
        self.cell(0, 12, "Your Quick Wins Checklist", align="C")
        self.ln(6)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(200, 210, 230)
        self.cell(0, 8, "Do these TODAY to start seeing results", align="C")
        self.ln(16)

        for item in quick_wins:
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(*COLOR_ACCENT)
            self.cell(8, 8, "[x]", align="L")
            self.set_font("Helvetica", "", 11)
            self.set_text_color(255, 255, 255)
            self.multi_cell(0, 8, item)
            self.ln(3)

    def add_resources(self, resources):
        self.add_page()
        self.set_fill_color(*COLOR_LIGHT)
        self.rect(0, 0, self.w, self.h, "F")

        self.set_y(30)
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*COLOR_BG)
        self.cell(0, 12, "Resources & Next Steps", align="L")
        self.ln(14)

        self.set_font("Helvetica", "", 11)
        self.set_text_color(*COLOR_TEXT)
        for res in resources:
            self.cell(6, 8, ">>", align="L")
            self.multi_cell(0, 8, res)
            self.ln(2)

        self.ln(10)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*COLOR_BG)
        self.cell(0, 10, "Thank you for your purchase!")
        self.ln(8)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*COLOR_MID)
        self.multi_cell(
            0, 7,
            "If this guide helped you, please consider leaving a review. "
            "Your feedback helps others find this resource and motivates us to keep creating."
        )


def build_pdf(product: Dict) -> Path:
    """Build a complete PDF from product data. Returns the path to the saved file."""
    pdf = ProductPDF(product)

    pdf.add_cover()
    pdf.add_toc(product["chapters"])

    for i, chapter in enumerate(product["chapters"], 1):
        pdf.add_chapter(i, chapter)

    pdf.add_quick_wins(product.get("quick_wins", []))
    pdf.add_resources(product.get("resources", []))

    # Slugify title for filename
    slug = product["title"].lower()
    for ch in " /\\:*?\"<>|.,!":
        slug = slug.replace(ch, "-")
    slug = "-".join(part for part in slug.split("-") if part)[:60]

    output_path = PRODUCTS_DIR / f"{slug}.pdf"
    pdf.output(str(output_path))

    return output_path
