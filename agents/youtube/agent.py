"""
YouTube Script Agent
Researches trending topics, writes full video scripts, generates SEO metadata,
thumbnail concepts, and upload checklists — ready to film and publish.
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
    today_dir,
    datestamp,
)

AGENT_NAME = "youtube"
OUTPUTS_BASE = _REPO_ROOT / "outputs" / "youtube"

SUBREDDITS = [
    "learnprogramming",
    "personalfinance",
    "entrepreneur",
    "selfimprovement",
]

PROFITABLE_NICHES = ["finance", "productivity", "side hustles", "tech", "self improvement"]

SYSTEM_PROMPT = (
    "You are an expert YouTube content strategist and scriptwriter with deep knowledge "
    "of high-retention video formats, SEO, and monetisable niches (finance, productivity, "
    "side hustles, tech, self-improvement). You write in an engaging, conversational tone "
    "that keeps viewers watching and drives subscriber growth."
)


# ---------------------------------------------------------------------------
# Step 1 — Research
# ---------------------------------------------------------------------------

def _collect_reddit_titles() -> list[str]:
    """Fetch hot titles from all target subreddits and return a flat list."""
    all_titles: list[str] = []
    for sub in SUBREDDITS:
        try:
            titles = fetch_reddit_titles(sub, limit=15)
            all_titles.extend(titles)
        except Exception as exc:
            print(f"  [warn] could not fetch r/{sub}: {exc}")
    return all_titles


# ---------------------------------------------------------------------------
# Step 2 — Topic selection
# ---------------------------------------------------------------------------

def _pick_topic(titles: list[str]) -> dict:
    """Ask Claude to pick the best YouTube video topic from the Reddit titles."""
    titles_block = "\n".join(f"- {t}" for t in titles[:60])
    prompt = f"""You are selecting the single best topic for a profitable YouTube video from this list of trending Reddit post titles.

Trending titles:
{titles_block}

Profitable niches to target: {', '.join(PROFITABLE_NICHES)}

Pick the ONE topic that has the best combination of:
1. High search volume potential (people actively Google this)
2. Monetisation appeal (finance, career, side income, productivity, tech tools)
3. 10-15 minute content depth (not too shallow, not too deep)
4. Broad audience appeal

Return a JSON object with EXACTLY these keys:
{{
  "topic": "concise topic name (5-10 words)",
  "niche": "one of: finance | productivity | side hustles | tech | self improvement",
  "angle": "the specific compelling angle for this video (1 sentence)",
  "target_viewer": "who this video is for (1 sentence)",
  "why_trending": "why this topic is resonating right now (1 sentence)",
  "primary_keyword": "main SEO keyword phrase (3-6 words)",
  "secondary_keywords": ["keyword2", "keyword3", "keyword4"]
}}

Return ONLY the JSON object, no other text."""

    return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=800, smart=True)


# ---------------------------------------------------------------------------
# Step 3 — Full script
# ---------------------------------------------------------------------------

def _write_script(topic_data: dict) -> str:
    """Generate a complete 10-15 minute YouTube video script."""
    prompt = f"""Write a COMPLETE, ready-to-film YouTube video script for the following topic.

Topic: {topic_data['topic']}
Angle: {topic_data['angle']}
Target viewer: {topic_data['target_viewer']}
Primary keyword: {topic_data['primary_keyword']}
Niche: {topic_data['niche']}

Script requirements:
- Total length: 1,800-2,500 words (fills 10-15 minutes at average speaking pace)
- Written word-for-word — the creator should be able to read this directly into camera

Structure (use these exact section headers):
## HOOK (0:00-0:30)
[Attention-grabbing open — start with a bold statement, shocking stat, or relatable problem.
Do NOT start with "Hey guys welcome back". Create curiosity and promise value in the first 10 seconds.]

## INTRO & PROMISE (0:30-1:30)
[Briefly introduce yourself, what the video covers, and the clear outcome the viewer will get.
Include a "stay to the end because..." tease.]

## SECTION 1 — [descriptive title]
[Talking points + transitions. Include natural "B-roll cue:" annotations in brackets for visual variety.]

## SECTION 2 — [descriptive title]
[Same format]

## SECTION 3 — [descriptive title]
[Same format]

## SECTION 4 — [descriptive title]
[Same format]

## SECTION 5 — [descriptive title]
[Same format]

## MIDROLL RETENTION HOOK (at ~50% mark)
[A pattern interrupt or re-engagement line to keep viewers watching. One or two sentences max.]

## SECTION 6 — [descriptive title] (optional — include if content warrants it)
[Same format]

## SECTION 7 — [descriptive title] (optional)
[Same format]

## OUTRO & CTA (last 60 seconds)
[Summarise 3 key takeaways. Ask viewers to SUBSCRIBE with a specific reason why ("If you want more videos on X...").
Ask a COMMENT prompt question to drive engagement. Mention next video.]

Formatting rules:
- B-roll cues look like: [B-ROLL: screen recording of dashboard]
- Emphasis looks like: *emphasise this word*
- Pause/breath looks like: [pause]
- Write naturally — contractions, conversational language, short punchy sentences mixed with longer ones
- Every section must deliver genuine, specific, actionable value — no filler

Begin the script now:"""

    return generate(prompt, system=SYSTEM_PROMPT, max_tokens=4000, smart=True)


# ---------------------------------------------------------------------------
# Step 4 — SEO metadata
# ---------------------------------------------------------------------------

def _generate_metadata(topic_data: dict, script: str) -> dict:
    """Generate video title, description, tags, and thumbnail concept."""
    script_excerpt = script[:1200]  # First ~1200 chars for context
    prompt = f"""Based on this YouTube video script excerpt, generate complete SEO metadata.

Topic: {topic_data['topic']}
Primary keyword: {topic_data['primary_keyword']}
Secondary keywords: {', '.join(topic_data.get('secondary_keywords', []))}
Niche: {topic_data['niche']}

Script opening:
{script_excerpt}

Generate a JSON object with EXACTLY these keys:

{{
  "video_title": "Compelling YouTube title, 60-70 chars, includes primary keyword, has a number or power word, creates curiosity",
  "description": "Full 500-word SEO-optimised video description. Structure: 2-sentence hook paragraph, timestamps (00:00 Intro, etc.), 3-paragraph detail about video content, 3 relevant links placeholders [LINK], call to subscribe, 5 relevant hashtags at end. Use the primary keyword naturally 2-3 times.",
  "tags": [
    "tag1", "tag2", "tag3", "tag4", "tag5",
    "tag6", "tag7", "tag8", "tag9", "tag10",
    "tag11", "tag12", "tag13", "tag14", "tag15"
  ],
  "thumbnail_concept": {{
    "text_overlay": "3-5 words max for thumbnail text (big, bold, provocative)",
    "background": "detailed description of background visual (colour, scene, photo style)",
    "subject": "description of person/subject in thumbnail and their expression/pose",
    "design_notes": "2-3 specific design instructions (font style, colour contrast, arrows, etc.)",
    "emotion": "the primary emotion this thumbnail should trigger in a viewer scrolling YouTube"
  }},
  "end_screen_suggestion": "What to show on the end screen (2 video recommendations + subscribe button placement)",
  "pinned_comment": "Write the pinned comment the creator should post (include timestamps + engagement question)"
}}

Return ONLY the JSON object."""

    return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=2500, smart=True)


# ---------------------------------------------------------------------------
# Step 5 — Upload checklist
# ---------------------------------------------------------------------------

def _generate_upload_checklist(topic_data: dict, metadata: dict) -> str:
    """Generate a step-by-step upload checklist."""
    title = metadata.get("video_title", topic_data["topic"])
    prompt = f"""Write a detailed step-by-step upload checklist for this YouTube video.

Video title: {title}
Niche: {topic_data['niche']}

The checklist should be a plain text document covering every step from finishing filming to the video going live and being promoted. Include:

1. Pre-upload file preparation (naming, resolution, codec specs)
2. YouTube Studio upload steps (all fields to fill in, in order)
3. Thumbnail upload and optimisation tips
4. End screen and cards setup
5. Monetisation settings (if eligible)
6. Premiere vs. publish immediately decision
7. First 24-hour promotion checklist (community post, shorts teaser, pinned comment, reply to early comments)
8. SEO check before publishing
9. Cross-promotion steps (social media posts — what to write for Twitter/X, LinkedIn, Instagram caption)

Format as a numbered checklist with clear section headers. Be specific — mention exact YouTube Studio UI locations.
Write it as if it's instructions for someone who has uploaded a few videos before but wants to be thorough."""

    return generate(prompt, system=SYSTEM_PROMPT, max_tokens=2000, smart=False)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(config: dict = None) -> dict:
    """
    Run the YouTube Script Agent.

    Returns:
        {
            "status": "success" | "error",
            "outputs": [list of absolute file paths],
            "topic": "...",
            "title": "...",
            "error": "..." (only on failure)
        }
    """
    config = config or {}
    outputs: list[str] = []

    try:
        print("[youtube] Collecting Reddit titles...")
        titles = _collect_reddit_titles()

        if not titles:
            # Fallback seed topics when Reddit is unreachable
            titles = [
                "How I paid off $40k in debt in 18 months on a $55k salary",
                "The productivity system that changed my life (after trying 12 others)",
                "I built a side hustle that makes $3k/month working 10 hours a week",
                "Best free AI tools in 2024 that replaced my paid subscriptions",
                "Why most people never achieve financial independence (and how to fix it)",
            ]
            print(f"  [warn] No Reddit titles fetched — using {len(titles)} seed topics")
        else:
            print(f"  Collected {len(titles)} titles from Reddit")

        print("[youtube] Selecting best topic...")
        topic_data = _pick_topic(titles)
        print(f"  Topic: {topic_data['topic']}")
        print(f"  Niche: {topic_data['niche']}")
        print(f"  Keyword: {topic_data['primary_keyword']}")

        print("[youtube] Writing full video script...")
        script = _write_script(topic_data)
        print(f"  Script length: {len(script.split())} words")

        print("[youtube] Generating SEO metadata...")
        metadata = _generate_metadata(topic_data, script)

        print("[youtube] Generating upload checklist...")
        checklist = _generate_upload_checklist(topic_data, metadata)

        # Build output directory
        out_dir = today_dir(OUTPUTS_BASE)

        # Save script.txt
        script_path = out_dir / "script.txt"
        video_title = metadata.get("video_title", topic_data["topic"])
        script_header = (
            f"VIDEO TITLE: {video_title}\n"
            f"TOPIC: {topic_data['topic']}\n"
            f"NICHE: {topic_data['niche']}\n"
            f"PRIMARY KEYWORD: {topic_data['primary_keyword']}\n"
            f"GENERATED: {datestamp()}\n"
            + "=" * 60 + "\n\n"
        )
        save_text(script_path, script_header + script)
        outputs.append(str(script_path))
        log_output(AGENT_NAME, f"Script: {video_title}", str(script_path), topic_data["niche"])

        # Save metadata.json
        metadata_path = out_dir / "metadata.json"
        full_metadata = {
            "generated_date": datestamp(),
            "topic": topic_data,
            "video_title": video_title,
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "thumbnail_concept": metadata.get("thumbnail_concept", {}),
            "end_screen_suggestion": metadata.get("end_screen_suggestion", ""),
            "pinned_comment": metadata.get("pinned_comment", ""),
        }
        save_json(metadata_path, full_metadata)
        outputs.append(str(metadata_path))
        log_output(AGENT_NAME, f"Metadata: {video_title}", str(metadata_path), "SEO metadata + thumbnail")

        # Save upload_checklist.txt
        checklist_path = out_dir / "upload_checklist.txt"
        checklist_header = (
            f"UPLOAD CHECKLIST\n"
            f"Video: {video_title}\n"
            f"Date: {datestamp()}\n"
            + "=" * 60 + "\n\n"
        )
        save_text(checklist_path, checklist_header + checklist)
        outputs.append(str(checklist_path))
        log_output(AGENT_NAME, f"Checklist: {video_title}", str(checklist_path), "Upload workflow")

        print(f"[youtube] Done. Saved {len(outputs)} files to {out_dir}")
        return {
            "status": "success",
            "outputs": outputs,
            "topic": topic_data["topic"],
            "title": video_title,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[youtube] ERROR: {exc}\n{tb}")
        return {
            "status": "error",
            "outputs": outputs,
            "topic": "",
            "title": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run()
    print("\n" + "=" * 56)
    print("YOUTUBE AGENT RESULT")
    print("=" * 56)
    print(f"Status : {result['status']}")
    print(f"Topic  : {result.get('topic', 'N/A')}")
    print(f"Title  : {result.get('title', 'N/A')}")
    print(f"Outputs: {len(result.get('outputs', []))} files")
    for path in result.get("outputs", []):
        print(f"  - {path}")
    if result.get("error"):
        print(f"Error  : {result['error']}")
    print("=" * 56)
