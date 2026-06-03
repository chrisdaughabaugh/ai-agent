"""
Generates high-quality digital product content using Claude Haiku.
Produces structured ebook/guide content ready for PDF assembly.
"""

import os
import json
from typing import Dict
import anthropic


MODEL = "claude-haiku-4-5-20251001"
client = None


def get_client() -> anthropic.Anthropic:
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client


def generate_product(idea: Dict) -> Dict:
    """
    Generate a complete digital product (ebook/guide) from a product idea.
    Returns structured content with title, subtitle, chapters, and marketing copy.
    """
    trending_note = ""
    if idea.get("trending_context"):
        trending_note = f"\nTrending topics in this space right now: {', '.join(idea['trending_context'][:4])}"

    prompt = f"""You are an expert digital product creator. Create a comprehensive, actionable guide/ebook that will genuinely help people and sell well on Gumroad.

Product concept:
- Title: {idea['title']}
- Niche: {idea['niche']}
- Target audience: {idea['audience']}
- Key pain point to solve: {idea['pain_point']}
- Primary keyword: {idea['primary_keyword']}{trending_note}

Generate the complete product as a JSON object with this exact structure:
{{
  "title": "compelling, specific title (not generic)",
  "subtitle": "one-line value proposition that makes people want to buy",
  "tagline": "short punchy phrase for marketing",
  "description": "2-3 paragraph sales description for the Gumroad listing page (benefit-focused, no fluff)",
  "price_cents": <price in cents, e.g. 1200 for $12.00>,
  "chapters": [
    {{
      "title": "Chapter title",
      "content": "750-1000 words of genuinely helpful, actionable content with specific steps, examples, and tips. Use plain text with paragraph breaks (newline separated). No markdown."
    }}
  ],
  "quick_wins": ["5 immediate action items the reader can do today"],
  "resources": ["3-5 free tools or resources mentioned in the guide"],
  "tweet": "Twitter/X post to promote this product (under 280 chars, no hashtag spam)",
  "reddit_post": "Reddit post title + 2-paragraph body to share in relevant subreddits"
}}

Requirements:
- Include exactly 5 chapters
- Each chapter must be substantive (750+ words), specific, and immediately actionable
- No filler content — every sentence must add value
- Write in a friendly, expert tone — like advice from a successful friend
- The product should be worth $10-20 to the target buyer
- Return ONLY the JSON object, no other text"""

    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resp.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    product = json.loads(raw)
    product["niche"] = idea["niche"]
    product["primary_keyword"] = idea["primary_keyword"]
    product["audience"] = idea["audience"]

    return product


def generate_cover_text(product: Dict) -> Dict:
    """Generate the text content for the product cover page."""
    return {
        "title": product["title"],
        "subtitle": product["subtitle"],
        "tagline": product.get("tagline", ""),
        "niche": product["niche"],
    }
