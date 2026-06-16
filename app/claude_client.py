"""Thin Anthropic Claude wrapper. Reads model + key from config."""
import json
import re
from anthropic import Anthropic
from .config import cfg

_client = None


def client() -> Anthropic:
    global _client
    if _client is None:
        if not cfg.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        _client = Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    return _client


def complete(system: str, user: str, max_tokens: int = 2000, temperature: float = 0.4) -> str:
    msg = client().messages.create(
        model=cfg.ANTHROPIC_MODEL_NAME,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if block.type == "text").strip()


def complete_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """Ask Claude for JSON and parse it robustly."""
    raw = complete(
        system + "\n\nRespond with ONLY valid JSON. No markdown, no prose.",
        user,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return _extract_json(raw)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise
