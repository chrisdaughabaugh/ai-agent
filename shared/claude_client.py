"""Shared Claude client with prompt caching for cost efficiency."""

import os
import anthropic

_client = None
FAST_MODEL = "claude-haiku-4-5-20251001"
SMART_MODEL = "claude-sonnet-4-6"


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def generate(prompt: str, system: str = "", max_tokens: int = 4000, smart: bool = False) -> str:
    """Generate text with Claude. Uses Haiku by default to minimize cost."""
    model = SMART_MODEL if smart else FAST_MODEL
    messages = [{"role": "user", "content": prompt}]
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    resp = get_client().messages.create(**kwargs)
    return resp.content[0].text.strip()


def generate_json(prompt: str, system: str = "", max_tokens: int = 4000, smart: bool = False) -> dict:
    """Generate and parse a JSON response from Claude."""
    import json
    raw = generate(prompt, system=system, max_tokens=max_tokens, smart=smart)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
