"""
LLM client supporting Groq (free) and Anthropic (paid).
Priority: uses Groq if GROQ_API_KEY is set, falls back to Anthropic.

Free tier: groq.com — no credit card, ~14,400 requests/day.
"""

import os
import json

# Groq models (free tier)
GROQ_FAST  = "llama-3.1-8b-instant"   # fast, cheap tasks
GROQ_SMART = "llama-3.3-70b-versatile" # longer content, better quality

# Anthropic models (fallback, paid)
ANT_FAST  = "claude-haiku-4-5-20251001"
ANT_SMART = "claude-sonnet-4-6"

_groq_client = None
_ant_client  = None


def _provider() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise EnvironmentError(
        "No LLM API key found. Set GROQ_API_KEY (free at groq.com) "
        "or ANTHROPIC_API_KEY in your environment / GitHub secrets."
    )


def _groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


def _anthropic():
    global _ant_client
    if _ant_client is None:
        import anthropic
        _ant_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _ant_client


def generate(prompt: str, system: str = "", max_tokens: int = 4000, smart: bool = False) -> str:
    """Generate text using the available LLM provider."""
    provider = _provider()

    if provider == "groq":
        model = GROQ_SMART if smart else GROQ_FAST
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = _groq().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()

    else:  # anthropic
        model = ANT_SMART if smart else ANT_FAST
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        resp = _anthropic().messages.create(**kwargs)
        return resp.content[0].text.strip()


def generate_json(prompt: str, system: str = "", max_tokens: int = 4000, smart: bool = False) -> dict:
    """Generate and parse a JSON response."""
    raw = generate(prompt, system=system, max_tokens=max_tokens, smart=smart)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
