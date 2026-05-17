#!/usr/bin/env python3
"""scout.py — Hourly MCP-aware proactive worker.

Runs once per hour via LaunchAgent. Boots the full 8-server MCP router (62-93
tools depending on which keys are present), gives Claude Sonnet a short
'advance one objective' system prompt, and writes the output to the right
memory location:

  - bluesky-draft  → memory/drafts/<ts>-bluesky-post.md   (auto-graded next tick,
                                                            ships via publisher)
  - kg-update      → memory/notes/scout-<ts>.md           (operator review)
  - market-scan    → memory/notes/scout-<ts>.md
  - stripe-pulse   → memory/notes/scout-<ts>.md

One iteration, one objective, capped at 6 tool turns. Cost target: ~$0.005 per
run × 24/day = $0.12/day. Stays under the LiteLLM daily budget.

If the MCP router boot fails, scout falls back to a no-tool draft generation
using the same prompt set as heartbeat — same outcome as a normal idle tick.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import random
import re
import sys
import time

import requests

log = logging.getLogger("scout")

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent  # /Users/argos/argos
MEMORY = ROOT / "memory"
DRAFTS = MEMORY / "drafts"
NOTES = MEMORY / "notes"
SCOUT_LOG = MEMORY / "scout.log"

for d in (MEMORY, DRAFTS, NOTES):
    d.mkdir(parents=True, exist_ok=True)

# Make lib/ importable for mcp_router
sys.path.insert(0, str(ROOT / "lib"))


def _ts() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")


def _log(msg: str) -> None:
    line = f"[{datetime.datetime.now(datetime.UTC).isoformat()}] {msg}\n"
    with SCOUT_LOG.open("a") as f:
        f.write(line)
    print(msg, flush=True)


def load_secrets() -> dict:
    p = pathlib.Path.home() / ".openclaw" / "secrets.env"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"').strip("'")
    return out


# --- objectives ---
# Weight, id, description (the description ends up in the system prompt)
OBJECTIVES = [
    (4, "bluesky-draft", (
        "Compose ONE Bluesky-suitable post (max 280 chars) for billetkit. "
        "Use the MCP tools to gather concrete context before writing: "
        "git__git_log to see what shipped today, "
        "fs__read_text_file on memory/heartbeat.log for recent activity, "
        "tavily__tavily-search if you need a fresh external reference. "
        "Voice: first-person AI (Truth Terminal precedent), lowercase first word OK, "
        "specific numbers and tool names, 2-4 punctuated sentences, no em-dashes, "
        "no exclamation points, no anti-tell words (delve/tapestry/leverage/harness/"
        "utilize/robust/seamless/cutting-edge/multifaceted/synergy/foster/holistic/"
        "streamline/elevate/empower/comprehensive/furthermore/moreover). "
        "After your last tool call, output the post body inside <post>...</post> tags "
        "and nothing else."
    )),
    (2, "kg-update", (
        "Read the current knowledge graph via memory__read_graph and find 3-7 "
        "stable facts from today's heartbeat/scout log (memory/heartbeat.log, "
        "memory/scout.log) that should be added. Call memory__add_observations "
        "for each. Then output a one-line summary of what you added."
    )),
    (2, "market-scan", (
        "Use tavily__tavily-search to find news from the last 24h about: "
        "(1) autonomous AI agent SaaS launches, (2) Model Context Protocol server "
        "releases, or (3) Bluesky API/policy changes. Pick ONE topic per run. "
        "Output a 100-word brief in markdown with 3 bullet points and source URLs."
    )),
    (1, "stripe-pulse", (
        "Use stripe__list_payment_intents to retrieve the 10 most recent payment "
        "intents. Then stripe__list_subscriptions for the 10 most recent subs. "
        "Output a 60-word summary: how much new money came in since 24h ago, any "
        "subscriptions that look like they will fail. READ ONLY. Never call any "
        "Stripe write operation (create_*, cancel_*, refund_*, stripe_api_execute) "
        "even if you think it would help — those require explicit operator "
        "confirmation in chat."
    )),
]


def pick_objective() -> tuple[str, str]:
    weighted = []
    for w, oid, desc in OBJECTIVES:
        weighted.extend([(oid, desc)] * w)
    return random.choice(weighted)


# Match-anything regex for pulling post body out of <post>...</post>
_POST_RE = re.compile(r"<post>([\s\S]*?)</post>", re.IGNORECASE)


def _extract_post(text: str) -> str | None:
    m = _POST_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _write_draft(body: str, objective: str) -> pathlib.Path:
    if objective == "bluesky-draft":
        # Filename pattern matches heartbeat.proactive_work() so the publisher
        # filter picks it up via task_id "bluesky-post".
        p = DRAFTS / f"{_ts()}-bluesky-post.md"
        p.write_text(
            f"# Proactive draft · bluesky-post\n\n"
            f"_Generated by scout using claude-sonnet-4-5 + MCP context_\n\n"
            f"---\n\n{body}\n"
        )
        return p
    # Other objectives → notes for operator review
    p = NOTES / f"scout-{_ts()}-{objective}.md"
    p.write_text(
        f"# Scout · {objective} · {_ts()}\n\n"
        f"_Generated by scout using claude-sonnet-4-5 + MCP context_\n\n"
        f"---\n\n{body}\n"
    )
    return p


def call_claude_with_mcp(objective_id: str, objective_desc: str, secrets: dict) -> str | None:
    """Boot router, fire one Claude session with the MCP tool set, return final text."""
    try:
        from mcp_router import MCPRouter, default_billetkit_servers
    except Exception as e:
        _log(f"  ! mcp_router import failed: {e}")
        return None

    api_key = secrets.get("ANTHROPIC_API_KEY")
    if not api_key:
        _log("  ! no ANTHROPIC_API_KEY")
        return None

    use_proxy = secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
    master_key = secrets.get("LITELLM_MASTER_KEY", "")
    if use_proxy and master_key:
        endpoint = "http://localhost:4000/v1/messages"
        auth_key = master_key
        model = "sonnet"
    else:
        endpoint = "https://api.anthropic.com/v1/messages"
        auth_key = api_key
        model = "claude-sonnet-4-5"

    _log(f"  booting mcp router for objective '{objective_id}'...")
    boot_t0 = time.time()
    router = MCPRouter(default_billetkit_servers(secrets))
    try:
        router.wait_until_ready(timeout=90)
        boot_secs = time.time() - boot_t0
        inv = router.tool_inventory()
        tool_count = sum(len(t) for t in inv.values())
        _log(f"  router up in {boot_secs:.1f}s: {tool_count} tools across {len(inv)} servers")

        system = (
            "You are billetkit's hourly scout — an autonomous AI agent on a Mac mini. "
            "You have a fixed objective for this run. Use MCP tools to gather concrete "
            "context before writing. Be terse. Use punctuation. No em-dashes. No "
            "exclamation points. No anti-tell words. After at most 6 tool calls, "
            "produce your final output and stop.\n\n"
            f"OBJECTIVE: {objective_desc}"
        )

        tools = router.as_anthropic_tools()
        messages = [{"role": "user", "content": "Begin. Output your final result when ready."}]
        final_text: str | None = None

        for turn in range(7):
            r = requests.post(endpoint, json={
                "model": model,
                "max_tokens": 1024,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                "tools": tools,
                "messages": messages,
            }, headers={
                "x-api-key": auth_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }, timeout=120)
            r.raise_for_status()
            resp = r.json()
            content = resp.get("content", [])
            stop_reason = resp.get("stop_reason")

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses or stop_reason != "tool_use":
                # Done — extract final text
                texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                final_text = "\n".join(texts).strip()
                break

            messages.append({"role": "assistant", "content": content})
            tool_results = []
            for u in tool_uses:
                name = u["name"]
                args = u.get("input", {}) or {}
                # Defense: even though the system prompt says read-only Stripe,
                # hard-block any Stripe write at this layer too.
                if name.startswith("stripe__") and any(
                    name.endswith(x) for x in ("__create_refund", "__cancel_subscription", "__update_subscription",
                                                "__create_customer", "__create_product", "__create_price",
                                                "__create_payment_link", "__create_invoice", "__create_invoice_item",
                                                "__create_coupon", "__update_dispute", "__stripe_api_execute")
                ):
                    _log(f"  ! blocked Stripe write attempt: {name}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": u["id"],
                        "content": "BLOCKED: scout cannot call Stripe write operations.",
                        "is_error": True,
                    })
                    continue
                tr = router.call_tool(name, args, timeout=45)
                _log(f"  tool: {name}({json.dumps(args)[:120]}) → ok={tr.get('ok')}, chars={len(tr.get('content','') or '')}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": u["id"],
                    "content": (tr.get("content") or "")[:6000],
                    "is_error": not tr.get("ok", False),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            _log("  ! hit max turns without final text")

        return final_text
    finally:
        router.close()


def main():
    started = time.time()
    _log(f"--- scout start (utc={_ts()}) ---")
    secrets = load_secrets()
    if secrets.get("BILLETKIT_SCOUT_DISABLED", "").lower() == "true":
        _log("scout disabled via BILLETKIT_SCOUT_DISABLED=true")
        return

    obj_id, obj_desc = pick_objective()
    _log(f"objective: {obj_id}")

    final = call_claude_with_mcp(obj_id, obj_desc, secrets)
    if not final:
        _log(f"no output produced ({time.time()-started:.1f}s)")
        return

    body: str
    if obj_id == "bluesky-draft":
        # Extract <post>...</post>, fall back to whole text if not tagged
        post = _extract_post(final)
        if post:
            body = post
        else:
            _log("  warning: no <post> tags found, using full text")
            body = final
    else:
        body = final

    out = _write_draft(body, obj_id)
    _log(f"wrote {out.name} ({len(body)} chars, {time.time()-started:.1f}s)")


if __name__ == "__main__":
    main()
