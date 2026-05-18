"""billetkit-voice-grader — MCP server exposing AI-slop detection + 2026 anti-tell voice grading.

Wraps two functions any AI-content pipeline needs but most operators rebuild from scratch:

  ai_slop_score(text)     → Pangram/GPTZero-style probability that this text is AI-generated
  voice_grade(text)       → strict grade against 2026 anti-tell wordlist + structural patterns

Both are calibrated against the May 2026 research on actual detector behavior. Returns
JSON with score (0-100), flags, and a concrete rewrite hint. Cheap (~$0.0005/call via
Haiku-class model; runs locally if OLLAMA_BASE_URL is set).

Use case: drop in front of any LLM that produces customer-facing prose. Block publish
if score >= your threshold.
"""
import asyncio
import json
import os
import re
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import httpx


SLOP_RUBRIC = """You are a calibrated AI-detection simulator. Score how likely Pangram/GPTZero/Originality.ai would flag the input text as AI-generated. Output ONLY valid JSON.

Patterns that INCREASE the score:
- Uniform sentence-length std-dev < 6 words → +25
- Em-dash density > 1 per 200 words → +15
- Anti-tell word hits (delve, tapestry, leverage, harness, multifaceted, comprehensive, furthermore, moreover, navigate, robust, seamless, cutting-edge, holistic, synergy, foster, streamline, elevate, empower, ecosystem, paradigm, unlock, vibrant, compelling, endeavor, underscore) → +10 per hit, capped at +50
- Three-item parallel lists "X, Y, and Z" more than once → +20
- Zero contractions in text > 40 words → +20
- Zero typos / one-word sentences / fragments → +15
- Sign-offs ("hope this helps", "let me know if", "happy to chat", "TL;DR", "in conclusion") → +25
- Markdown headers in casual prose → +15
- Passive voice density > 15% → +10
- Stack of transitions (Moreover/Furthermore/Additionally same para) → +20
- Generic "modern tech enthusiast" / "build better code" abstractions → +15

Patterns that DECREASE the score:
- Specific number, named entity, real URL, model SKU in first 2 sentences → -15
- Sentence-length std-dev >= 9 → -15
- Lowercase first word OR plausible typo (~1 per 400 words) → -10
- Sentence fragments or one-word sentences → -10
- Mid-thought parenthetical asides → -5
- Numbers that don't round → -10
- First-person identity claim that names the speaker → -5

Calibration:
- 0-30: human-passable
- 31-60: borderline, ~60% survive
- 61-79: likely flagged by Pangram
- 80-100: hard fail across detectors

Output (strict JSON, no fence):
{"ai_prob": 0-100, "flags": ["..."], "rewrite_hint": "one-line fix"}"""


VOICE_RUBRIC = """You grade prose against the 2026 anti-tell voice rules. Output ONLY JSON.

REJECT hits (any one = reject):
1. Anti-tell wordlist: delve, tapestry, landscape (metaphor), realm, navigate, leverage, harness,
   utilize, robust, seamless, cutting-edge, game-changer, pivotal, multifaceted, comprehensive,
   furthermore, moreover, additionally, crucial, vibrant, compelling, endeavor, streamline,
   underscore, testament, underpinnings, ever-evolving, embark on a journey, in today's fast-paced
   world, let's dive in, it's worth noting, that being said, when it comes to, in the realm of,
   at the end of the day, navigate the complexities, unlock the potential, paradigm shift,
   holistic approach, synergy, foster, fostering, ecosystem (metaphor), imagine a world where,
   hope this helps, let me know if, happy to chat, feel free to, empower, unleash, elevate.
2. Sign-offs: "hope this helps", "let me know if", "happy to chat", "TL;DR:", "Here's the thing:".
3. Em-dash density > 1 per 200 words.
4. Three-item parallel lists more than once.
5. Zero contractions in posts > 40 words.
6. **bold** markdown in casual posts. Emoji bullets.
7. Passive voice density > 15%.
8. Exclamation points (one OK; two+ rejects).

PASS criteria (need >=3 of 5):
- Specific number, named entity, real URL, or model SKU in first 2 sentences.
- Sentence-length std-dev >= 9.
- At least one fragment or one-word sentence.
- Lowercase first word OR plausible typo.
- First-person framing where relevant.

Output: {"verdict": "APPROVE"|"REJECT"|"ESCALATE", "score": 0-10, "failure_modes": ["..."], "rewrite_hint": "..."}"""


# ---- Backend selection: Anthropic (if API key) or Ollama (if URL) ----

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:32b")


async def call_anthropic(system: str, user: str, max_tokens: int = 400) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set and OLLAMA_BASE_URL also unset")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


async def call_ollama(system: str, user: str, max_tokens: int = 400) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.2},
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


async def call_model(system: str, user: str, max_tokens: int = 400) -> str:
    if OLLAMA_BASE_URL:
        return await call_ollama(system, user, max_tokens)
    return await call_anthropic(system, user, max_tokens)


def extract_json(text: str) -> dict:
    """Robust JSON extraction — handle code fences + prose-wrapped output."""
    text = text.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {"ai_prob": 50, "verdict": "ESCALATE", "flags": ["unparseable grader output"]}


# ---- MCP server ----

server = Server("billetkit-voice-grader")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ai_slop_score",
            description=(
                "Score how likely a piece of text would be flagged as AI-generated by detectors "
                "like Pangram/GPTZero/Originality.ai. Returns ai_prob (0-100), flags, and a "
                "concrete rewrite hint. Use as a pre-publish gate on any AI-generated prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to score"},
                    "threshold": {
                        "type": "integer",
                        "default": 70,
                        "description": "Convenience: return publish_safe=True if ai_prob < threshold",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="voice_grade",
            description=(
                "Grade prose against the 2026 anti-tell wordlist + structural patterns. Returns "
                "verdict (APPROVE/REJECT/ESCALATE), score 0-10, named failure modes, and a "
                "rewrite hint. Tighter than ai_slop_score for voice-quality concerns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to grade"},
                },
                "required": ["text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
    text = args.get("text", "")
    if not text:
        return [TextContent(type="text", text=json.dumps({"error": "text is required"}))]

    if name == "ai_slop_score":
        threshold = args.get("threshold", 70)
        result_text = await call_model(SLOP_RUBRIC, f"Text to score:\n\n{text}")
        result = extract_json(result_text)
        result["publish_safe"] = int(result.get("ai_prob", 100)) < int(threshold)
        result["threshold"] = threshold
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "voice_grade":
        result_text = await call_model(VOICE_RUBRIC, f"Text to grade:\n\n{text}")
        result = extract_json(result_text)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
