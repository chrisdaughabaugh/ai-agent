"""
Newsletter Agent
Rotates through profitable niches, researches trending stories from Reddit,
writes a complete HTML + plain-text newsletter issue, and saves all outputs
ready to paste into Mailchimp, Beehiiv, or any ESP.
"""

import sys
import json
import traceback
from pathlib import Path

# Ensure the repo root is on sys.path so shared/ is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import (
    slugify,
    fetch_reddit_titles,
    save_text,
    save_json,
    datestamp,
)

AGENT_NAME = "newsletter"
OUTPUTS_BASE = _REPO_ROOT / "outputs" / "newsletters"
STATE_FILE = _REPO_ROOT / "data" / "newsletter_state.json"

# Rotation order for niches — agent cycles through these in sequence
NICHES = [
    "AI tools",
    "personal finance",
    "productivity",
    "side hustles",
    "mental health",
]

# Reddit sources for each niche
NICHE_SUBREDDITS = {
    "AI tools": ["MachineLearning", "artificial", "ChatGPT", "singularity"],
    "personal finance": ["personalfinance", "financialindependence", "frugal", "povertyfinance"],
    "productivity": ["productivity", "getdisciplined", "selfimprovement", "timemanagement"],
    "side hustles": ["sidehustle", "entrepreneur", "passive_income", "WorkOnline"],
    "mental health": ["mentalhealth", "anxiety", "selfimprovement", "meditation"],
}

SYSTEM_PROMPT = (
    "You are an expert newsletter writer and content curator who specialises in creating "
    "high-value, engaging email newsletters for modern professionals. You write in a warm, "
    "intelligent, slightly witty tone — like a knowledgeable friend sharing the most useful "
    "things they found this week. Your newsletters have high open rates and strong referral "
    "growth because every issue delivers genuine, actionable value."
)


# ---------------------------------------------------------------------------
# State management — track issue number and last niche used
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Load newsletter state (issue number, last niche index)."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"issue_number": 0, "last_niche_index": -1}


def _save_state(state: dict):
    """Persist updated newsletter state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _next_niche(state: dict) -> tuple[str, int]:
    """Return the next niche in rotation and its index."""
    next_index = (state.get("last_niche_index", -1) + 1) % len(NICHES)
    return NICHES[next_index], next_index


# ---------------------------------------------------------------------------
# Step 1 — Research: pull trending titles for the chosen niche
# ---------------------------------------------------------------------------

def _research_niche(niche: str) -> list[str]:
    """Fetch hot Reddit titles from all subreddits relevant to this niche."""
    subreddits = NICHE_SUBREDDITS.get(niche, ["selfimprovement"])
    all_titles: list[str] = []
    for sub in subreddits:
        try:
            titles = fetch_reddit_titles(sub, limit=12)
            if titles:
                all_titles.extend(titles)
                print(f"  r/{sub}: {len(titles)} titles")
            else:
                print(f"  r/{sub}: no titles returned")
        except Exception as exc:
            print(f"  [warn] r/{sub} failed: {exc}")
    return all_titles


# ---------------------------------------------------------------------------
# Step 2 — Select 5 best stories / tips from the raw title pool
# ---------------------------------------------------------------------------

def _select_stories(niche: str, raw_titles: list[str]) -> list[dict]:
    """Ask Claude to pick and summarise the 5 best stories for the newsletter."""
    titles_block = "\n".join(f"- {t}" for t in raw_titles[:60])

    fallback_titles = {
        "AI tools": [
            "10 AI tools that replaced my $500/month software stack",
            "GPT-4 just got a major update — here's what changed",
            "How I automate my entire content workflow with free AI tools",
            "The AI productivity tools power users won't stop talking about",
            "Why prompt engineering is the most valuable skill of 2024",
        ],
        "personal finance": [
            "How I built a 6-month emergency fund earning $45k/year",
            "The 'reverse budget' method that changed how I think about money",
            "Best high-yield savings accounts right now (rated and compared)",
            "I automated all my finances — here's the exact setup I use",
            "The index fund strategy that 90% of financial advisors won't tell you",
        ],
        "productivity": [
            "The 2-minute rule changed my mornings completely",
            "How I went from 200 unread emails to inbox zero every day",
            "Deep work protocol that doubled my output in 30 days",
            "The Pomodoro technique is outdated — try this instead",
            "One habit that eliminated my Sunday anxiety forever",
        ],
        "side hustles": [
            "How I made $4,200 last month selling digital templates on Etsy",
            "The freelance skill with the highest hourly rate in 2024",
            "Passive income streams that actually work (from someone who's tried 20+)",
            "How to land your first client with zero portfolio or experience",
            "The side hustle that scales while you sleep (no, it's not dropshipping)",
        ],
        "mental health": [
            "The journaling technique that therapists are quietly recommending to everyone",
            "How I stopped doomscrolling for good (90 days update)",
            "CBT techniques you can do yourself without a therapist",
            "What 'emotional regulation' actually means and why it matters",
            "The anxiety trick that works in under 2 minutes, backed by science",
        ],
    }

    if not raw_titles:
        raw_titles = fallback_titles.get(niche, fallback_titles["productivity"])
        titles_block = "\n".join(f"- {t}" for t in raw_titles)
        print(f"  [warn] No Reddit titles — using {len(raw_titles)} fallback seeds for '{niche}'")

    prompt = f"""You are curating a newsletter issue about "{niche}".

From these trending Reddit post titles, select and develop the 5 most valuable, interesting items for a professional newsletter audience.

Raw titles:
{titles_block}

For each selected item, you will flesh it out into a proper newsletter item. Some items may be directly based on a Reddit title, others may be inspired by a theme you notice in the titles.

Return a JSON array of exactly 5 objects. Each object must have:
{{
  "headline": "Newsletter-style headline (punchy, specific, benefit-driven, 8-12 words)",
  "source_context": "1 sentence explaining what trend or conversation inspired this item",
  "summary": "3-4 sentences of genuine, actionable insight — the key takeaway a busy reader needs. Be specific, not vague. Include a concrete tip, number, or example.",
  "why_it_matters": "1 sentence on why this is relevant right now",
  "action_item": "One specific thing the reader can do today related to this item (start with a verb)"
}}

Return ONLY the JSON array. No other text."""

    try:
        return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=2000, smart=True)
    except Exception as exc:
        print(f"  [warn] Story selection JSON parse failed: {exc} — retrying with simpler prompt")
        # Fallback: build minimal story list from titles directly
        return [
            {
                "headline": t[:80],
                "source_context": "Trending on Reddit",
                "summary": t,
                "why_it_matters": "Currently generating significant discussion online.",
                "action_item": "Research this topic further and apply one insight this week.",
            }
            for t in raw_titles[:5]
        ]


# ---------------------------------------------------------------------------
# Step 3 — Write the deep-dive tip section
# ---------------------------------------------------------------------------

def _write_deep_dive(niche: str, stories: list[dict]) -> dict:
    """Generate one substantial 'deep dive' tip section for the issue."""
    headlines = "\n".join(f"- {s['headline']}" for s in stories)

    prompt = f"""Write a "Deep Dive" section for a newsletter issue about "{niche}".

The other items in this issue cover these topics:
{headlines}

The Deep Dive should be a standalone, in-depth tip or framework that complements the issue's theme without repeating what the other items cover. It should be the most valuable, substantial piece of content in the newsletter.

Return a JSON object with:
{{
  "title": "Deep Dive section title (e.g. 'The Framework', 'This Week's Deep Dive', 'The Method')",
  "headline": "Specific, compelling headline for this deep dive (10-15 words)",
  "body": "400-500 word deep dive. Write in clear paragraphs. Include: a concrete problem statement, a specific framework or method (with named steps or a memorable acronym if appropriate), a real-world example of how to apply it, and a direct takeaway. No bullet lists — flowing prose with natural paragraph breaks.",
  "key_takeaway": "One sentence summary of the most important lesson",
  "further_reading": "Suggest one specific book, tool, or resource the reader can explore (name it specifically)"
}}

Return ONLY the JSON object."""

    try:
        return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=1500, smart=True)
    except Exception as exc:
        print(f"  [warn] Deep dive JSON parse failed: {exc}")
        return {
            "title": "This Week's Deep Dive",
            "headline": f"A Framework for Getting More From {niche.title()}",
            "body": generate(
                f"Write a 400-word practical tip about {niche} for a newsletter audience.",
                system=SYSTEM_PROMPT,
                max_tokens=600,
                smart=False,
            ),
            "key_takeaway": f"Small consistent actions in {niche} compound into significant results.",
            "further_reading": "Atomic Habits by James Clear",
        }


# ---------------------------------------------------------------------------
# Step 4 — Generate subject lines and preview text
# ---------------------------------------------------------------------------

def _generate_subject_lines(niche: str, stories: list[dict], issue_number: int) -> dict:
    """Generate two A/B subject lines and preview text."""
    headlines = "\n".join(f"- {s['headline']}" for s in stories[:5])

    prompt = f"""Write email subject lines for newsletter issue #{issue_number} about "{niche}".

Items in this issue:
{headlines}

Return a JSON object with:
{{
  "subject_a": "Subject line A — curiosity-driven, creates an open loop, 40-55 chars",
  "subject_b": "Subject line B — benefit/outcome-focused, specific number or result, 40-55 chars",
  "preview_text": "Email preview text that complements subject_a, 85-95 chars, adds intrigue without repeating the subject line",
  "from_name_suggestion": "Suggested sender name (e.g. 'Alex @ The Niche Letter')",
  "send_time_suggestion": "Best day/time to send this type of newsletter and why (1-2 sentences)"
}}

Return ONLY the JSON object."""

    try:
        return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=600, smart=False)
    except Exception as exc:
        print(f"  [warn] Subject line generation failed: {exc}")
        return {
            "subject_a": f"5 things shaping {niche} this week",
            "subject_b": f"Issue #{issue_number}: What's working in {niche} right now",
            "preview_text": f"Curated insights, one deep dive, and an action item you can use today.",
            "from_name_suggestion": "The Weekly Brief",
            "send_time_suggestion": "Tuesday or Thursday mornings between 7-9am local time tend to have the highest open rates for professional newsletters.",
        }


# ---------------------------------------------------------------------------
# Step 5 — Build full HTML email
# ---------------------------------------------------------------------------

def _build_html_email(
    niche: str,
    issue_number: int,
    stories: list[dict],
    deep_dive: dict,
    subject_data: dict,
) -> str:
    """Ask Claude to write the complete HTML email body."""

    stories_json = json.dumps(stories, indent=2)
    deep_dive_json = json.dumps(deep_dive, indent=2)

    prompt = f"""Write a complete, production-ready HTML email newsletter for issue #{issue_number} about "{niche}".

Subject line (A): {subject_data['subject_a']}
Preview text: {subject_data['preview_text']}

Stories to include:
{stories_json}

Deep Dive section:
{deep_dive_json}

Requirements:
- Write valid, inline-styled HTML email compatible with Gmail, Apple Mail, and Outlook
- Use a clean, readable single-column layout (max-width: 600px, centered)
- Colour palette: white background, dark charcoal text (#1a1a2e), accent colour appropriate for the niche
- Include these sections in order:
  1. Header: newsletter name "The Weekly Brief" + issue number + date ({datestamp()})
  2. Intro paragraph: 3-4 sentences welcoming the reader, teasing what's inside, warm and personal tone
  3. "What's Trending" section: all 5 curated items, each with headline, summary, why-it-matters, and action item (styled as cards or clearly separated blocks)
  4. Deep Dive section: prominently styled, full body text, key takeaway in a highlighted box, further reading
  5. Share CTA: "Know someone who'd love this? Forward it or share your referral link: [REFERRAL_LINK]" — styled as a friendly callout block
  6. Footer: unsubscribe link placeholder, social links placeholders, "You're receiving this because you subscribed at [WEBSITE]"

HTML best practices:
- All styles must be inline (no <style> blocks — many email clients strip them)
- Use table-based layout for email client compatibility
- Font stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif
- Font size: body 16px, headings 22-26px, footer 12px
- Line height: 1.6 for body text
- Provide the complete DOCTYPE through </html> — the full document, nothing truncated

Write the complete HTML now:"""

    return generate(prompt, system=SYSTEM_PROMPT, max_tokens=4000, smart=True)


# ---------------------------------------------------------------------------
# Step 6 — Build plain text version
# ---------------------------------------------------------------------------

def _build_plain_text(
    niche: str,
    issue_number: int,
    stories: list[dict],
    deep_dive: dict,
    subject_data: dict,
) -> str:
    """Generate a clean plain-text version of the newsletter."""
    lines = []
    separator = "=" * 60

    lines.append(f"THE WEEKLY BRIEF — Issue #{issue_number}")
    lines.append(f"Niche: {niche.title()} | Date: {datestamp()}")
    lines.append(separator)
    lines.append(f"Subject (A): {subject_data['subject_a']}")
    lines.append(f"Subject (B): {subject_data['subject_b']}")
    lines.append(f"Preview: {subject_data['preview_text']}")
    lines.append(separator)
    lines.append("")
    lines.append("Hello,")
    lines.append("")
    lines.append(
        f"Welcome to issue #{issue_number} of The Weekly Brief. "
        f"This week we're covering the most valuable things happening in {niche}. "
        "Grab a coffee and let's get into it."
    )
    lines.append("")
    lines.append(separator)
    lines.append("WHAT'S TRENDING THIS WEEK")
    lines.append(separator)
    lines.append("")

    for i, story in enumerate(stories, 1):
        lines.append(f"{i}. {story['headline'].upper()}")
        lines.append("")
        lines.append(story["summary"])
        lines.append("")
        lines.append(f"Why it matters: {story['why_it_matters']}")
        lines.append(f"Action item: {story['action_item']}")
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

    lines.append(separator)
    lines.append(f"{deep_dive['title'].upper()}: {deep_dive['headline']}")
    lines.append(separator)
    lines.append("")
    lines.append(deep_dive["body"])
    lines.append("")
    lines.append(f"KEY TAKEAWAY: {deep_dive['key_takeaway']}")
    lines.append(f"FURTHER READING: {deep_dive['further_reading']}")
    lines.append("")
    lines.append(separator)
    lines.append("SHARE THIS ISSUE")
    lines.append(separator)
    lines.append("")
    lines.append(
        "Know someone who would find this valuable? Forward this email or share your "
        "referral link: [REFERRAL_LINK]"
    )
    lines.append("")
    lines.append(separator)
    lines.append("")
    lines.append("You're receiving this because you subscribed at [WEBSITE].")
    lines.append("Unsubscribe: [UNSUBSCRIBE_LINK]")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(config: dict = None) -> dict:
    """
    Run the Newsletter Agent.

    Returns:
        {
            "status": "success" | "error",
            "outputs": [list of absolute file paths],
            "niche": "...",
            "issue_number": N,
            "subject_a": "...",
            "subject_b": "...",
            "error": "..." (only on failure)
        }
    """
    config = config or {}
    outputs: list[str] = []

    try:
        # Load state and determine this issue's niche + number
        state = _load_state()
        issue_number = state.get("issue_number", 0) + 1
        niche, niche_index = _next_niche(state)

        # Allow config override of niche
        if config.get("niche") and config["niche"] in NICHES:
            niche = config["niche"]
            niche_index = NICHES.index(niche)

        print(f"[newsletter] Issue #{issue_number} | Niche: {niche}")

        # Research
        print(f"[newsletter] Researching '{niche}' on Reddit...")
        raw_titles = _research_niche(niche)
        print(f"  Total titles collected: {len(raw_titles)}")

        # Select stories
        print("[newsletter] Selecting top 5 stories...")
        stories = _select_stories(niche, raw_titles)
        print(f"  Selected {len(stories)} stories")

        # Deep dive
        print("[newsletter] Writing deep dive section...")
        deep_dive = _write_deep_dive(niche, stories)
        print(f"  Deep dive: {deep_dive.get('headline', '(untitled)')}")

        # Subject lines
        print("[newsletter] Generating subject lines...")
        subject_data = _generate_subject_lines(niche, stories, issue_number)
        print(f"  Subject A: {subject_data['subject_a']}")
        print(f"  Subject B: {subject_data['subject_b']}")

        # Build email body
        print("[newsletter] Writing HTML email...")
        html_body = _build_html_email(niche, issue_number, stories, deep_dive, subject_data)

        # Build plain text
        print("[newsletter] Building plain text version...")
        plain_text = _build_plain_text(niche, issue_number, stories, deep_dive, subject_data)

        # Build metadata
        metadata = {
            "generated_date": datestamp(),
            "issue_number": issue_number,
            "niche": niche,
            "subject_a": subject_data["subject_a"],
            "subject_b": subject_data["subject_b"],
            "preview_text": subject_data["preview_text"],
            "from_name_suggestion": subject_data.get("from_name_suggestion", "The Weekly Brief"),
            "send_time_suggestion": subject_data.get("send_time_suggestion", ""),
            "stories": [
                {
                    "headline": s["headline"],
                    "action_item": s.get("action_item", ""),
                }
                for s in stories
            ],
            "deep_dive_headline": deep_dive.get("headline", ""),
            "further_reading": deep_dive.get("further_reading", ""),
            "story_count": len(stories),
        }

        # Determine output directory: outputs/newsletters/issue-N/
        out_dir = OUTPUTS_BASE / f"issue-{issue_number}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save email.html
        html_path = out_dir / "email.html"
        save_text(html_path, html_body)
        outputs.append(str(html_path))
        log_output(
            AGENT_NAME,
            f"Issue #{issue_number} HTML: {subject_data['subject_a']}",
            str(html_path),
            f"niche={niche}",
        )

        # Save plain_text.txt
        txt_path = out_dir / "plain_text.txt"
        save_text(txt_path, plain_text)
        outputs.append(str(txt_path))
        log_output(
            AGENT_NAME,
            f"Issue #{issue_number} Plain Text",
            str(txt_path),
            f"niche={niche}",
        )

        # Save metadata.json
        meta_path = out_dir / "metadata.json"
        save_json(meta_path, metadata)
        outputs.append(str(meta_path))
        log_output(
            AGENT_NAME,
            f"Issue #{issue_number} Metadata",
            str(meta_path),
            f"subjects + story list",
        )

        # Persist updated state
        _save_state({
            "issue_number": issue_number,
            "last_niche_index": niche_index,
            "last_run": datestamp(),
            "last_subject_a": subject_data["subject_a"],
        })

        print(f"[newsletter] Done. Saved {len(outputs)} files to {out_dir}")
        return {
            "status": "success",
            "outputs": outputs,
            "niche": niche,
            "issue_number": issue_number,
            "subject_a": subject_data["subject_a"],
            "subject_b": subject_data["subject_b"],
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[newsletter] ERROR: {exc}\n{tb}")
        return {
            "status": "error",
            "outputs": outputs,
            "niche": "",
            "issue_number": 0,
            "subject_a": "",
            "subject_b": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run()
    print("\n" + "=" * 56)
    print("NEWSLETTER AGENT RESULT")
    print("=" * 56)
    print(f"Status       : {result['status']}")
    print(f"Niche        : {result.get('niche', 'N/A')}")
    print(f"Issue #      : {result.get('issue_number', 'N/A')}")
    print(f"Subject A    : {result.get('subject_a', 'N/A')}")
    print(f"Subject B    : {result.get('subject_b', 'N/A')}")
    print(f"Outputs      : {len(result.get('outputs', []))} files")
    for path in result.get("outputs", []):
        print(f"  - {path}")
    if result.get("error"):
        print(f"Error        : {result['error']}")
    print("=" * 56)
