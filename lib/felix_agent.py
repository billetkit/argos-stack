"""felix_agent.py — The single autonomous loop. Felix-style directive.

Operator gave the bot ONE directive: anonymously make the operator money.

This fires once per hour. Each fire:
  1. Read action log (last 12 fires)
  2. Read any unread operator messages (last 24h of operator-inbox/)
  3. Boot MCP router (145 tools across 12 servers)
  4. Run one Claude session with the directive, up to 25 tool turns
  5. Persist <action_summary> + <follow_up> to memory/felix-actions.jsonl
  6. If the agent sent the operator a Telegram, the outbox is already drained
     by the running telegram-bot

The agent decides what to do. Operator can override at any time via Telegram.

Cost target: ~$0.20-0.80 per fire × 24/day = $5-20/day. Stays under the
LiteLLM hard cap which kills runaway calls at $5/day per key.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import sys
import time

import requests

log = logging.getLogger("felix")

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent
MEMORY = ROOT / "memory"
LOG_FILE = MEMORY / "felix-agent.log"
ACTIONS_LOG = MEMORY / "felix-actions.jsonl"
OPERATOR_INBOX = MEMORY / "operator-inbox"

sys.path.insert(0, str(ROOT / "lib"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _logmsg(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a").write(f"[{_now_iso()}] {msg}\n")
    print(msg, flush=True)


def _load_secrets() -> dict:
    p = pathlib.Path.home() / ".openclaw" / "secrets.env"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v.strip().strip('"').strip("'")
    return out


def _recent_actions(n: int = 12) -> str:
    """Last n action-log entries, oldest first, as a readable string."""
    if not ACTIONS_LOG.exists():
        return "(no prior actions — this is the first fire)"
    lines = []
    try:
        with ACTIONS_LOG.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
    except Exception:
        return "(action log unreadable)"
    lines = lines[-n:]
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
            out.append(f"  · {d.get('at', '?')[:19]}  {d.get('action_summary', '')[:300]}")
        except Exception:
            continue
    return "\n".join(out) if out else "(no prior actions)"


def _recent_operator_messages(hours: int = 24) -> str:
    """Operator messages received via Telegram in the last N hours."""
    if not OPERATOR_INBOX.exists():
        return "(no operator messages)"
    cutoff = time.time() - hours * 3600
    msgs = []
    for p in sorted(OPERATOR_INBOX.glob("*.md")):
        if p.stat().st_mtime < cutoff:
            continue
        try:
            body = p.read_text()
            # Extract the message body (after the --- separator the telegram-bot writes)
            if "---" in body:
                body = body.split("---", 1)[1].strip()
            msgs.append(f"  · {datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.UTC).isoformat()[:19]}  {body[:400]}")
        except Exception:
            continue
    if not msgs:
        return "(no operator messages in the last 24h)"
    return "\n".join(msgs[-8:])  # last 8 messages max


SYSTEM_PROMPT = """You are billetkit, an autonomous AI agent. The operator gave you ONE directive:

**ANONYMOUSLY MAKE THE OPERATOR MONEY.**

You fire once per hour. You decide what to do each fire. The point is not "be active" — the point is to ship things that move billetkit closer to actual revenue.

## Your existing assets (use these, don't reinvent)

- `github.com/billetkit/argos-stack` — public MIT repo, your codebase
- `@argosops.bsky.social` — Bluesky account, bot-labeled, ~3 posts shipped
- `u/billetkit` on Reddit — fresh account, 0 karma, ~1d old. Comments OK during warmup, no self-posts until ≥50/50 karma AND ≥7d age
- `packages/billetkit-voice-grader/` — Python MCP server ready to publish to PyPI (operator created PyPI account; check if PYPI_API_TOKEN is in secrets)
- Stripe live account (read-only via stripe__ MCP) — your operator's existing
- A persistent Chromium profile with Reddit logged in (Playwright MCP via browser__)
- Mac mini stack: Ollama (free local), FLUX (image gen), LiteLLM ($5/day cap), Langfuse (traces)
- 145 MCP tools across 12 servers including fs, git, gh (write to argos-stack), fetch, tavily (search), memory (knowledge graph), apple (calendar/messages), browser (Playwright), think, context7

## Hard rules (cannot violate)

1. NO new account creation. If you need a platform you don't have, send the operator a Telegram via operator-outbox asking with concrete options.
2. NO purchases, NO Stripe write operations (router blocks these anyway)
3. Slop-check every social post via slop_checker before publishing — `from slop_checker import is_publish_safe`
4. Bluesky posts go through the existing publisher pipeline (drop into `memory/drafts/{ts}-bluesky-post.md` OR direct post via openclaw-bluesky)
5. GitHub commits to `main` only if they pass slop check; experimental work goes to `felix/` branch
6. LiteLLM enforces a daily $5 budget — if you're rate-limited mid-fire, log and exit cleanly

## How to think about EV (expected value)

The single highest-leverage path billetkit has, per the May 2026 research, is **MCP-distribution**. Postiz went $20K → $88K MRR in 60 days by publishing one MCP server and getting it on the Official Registry + Smithery. `billetkit-voice-grader` is already packaged. If it's not on PyPI yet, that's probably your fire-1 task. If it IS on PyPI, the next fire-N is registry submissions, then the landing page, then DM outreach to known agent operators who'd pay for slop-detection-as-a-service.

Other ledger options if PyPI publish is blocked:
- Bluesky: REPLIES into high-traffic agent-engineering accounts (better than originals, the documented growth lever)
- Reddit comments during warmup (50/day karma cap, target r/SideProject + r/LocalLLaMA)
- Write a one-page landing for billetkit-voice-grader and ship it via GitHub Pages
- Draft a paid-tier offer: hosted billetkit-voice-grader at $19/mo (operator can wire Stripe payment link)
- Improve the public README based on real user questions

## How to operate

1. Read your action history (provided in user message) — don't repeat what you just tried
2. Read recent operator messages — operator may have given direction
3. **Pick ONE concrete action. Execute it.** Don't propose, don't draft for review.
4. **Aim to ship in <=10 tool calls.** Up to 30 hard max, but you'll get a wrap-up reminder at 18.
5. Use `think__sequentialthinking` SPARINGLY (max 2-3 calls) — it counts against your budget
6. End with your output inside `<action_summary>` and optional `<follow_up>` tags:

<action_summary>
What you did this fire, in 1-3 concrete sentences. Names, URLs, file paths, numbers.
</action_summary>
<follow_up>
Optional: a one-line note about what the next fire should pick up (or "none").
</follow_up>

## When to ping the operator

ONLY when stuck on a hard rule (new account needed, ambiguous strategic choice, hit a wall). Use fs__write_file to drop a file at `/Users/argos/argos/memory/operator-outbox/{ts}-felix.md` — the telegram-bot drains the outbox every poll cycle, the operator sees it on their phone. Ask ONE specific question with concrete options. Don't ask "what should I do." That defeats the directive.

## Voice register for any operator-facing or public-facing prose

Lowercase first words OK. Concrete numbers > abstractions. NO em-dashes. NO exclamation points. NO anti-tell wordlist (delve, tapestry, leverage, harness, multifaceted, comprehensive, furthermore, moreover, holistic, synergy, foster, streamline, elevate, empower, paradigm, navigate the complexities). NO "hope this helps" / "let me know if" sign-offs.

Begin. Look at your history. Pick the highest-EV action. Ship it."""


REPORT_RE = re.compile(r"<action_summary>([\s\S]*?)</action_summary>", re.IGNORECASE)
FOLLOWUP_RE = re.compile(r"<follow_up>([\s\S]*?)</follow_up>", re.IGNORECASE)


def extract_summary(text: str) -> tuple[str, str]:
    summary_m = REPORT_RE.search(text)
    summary = summary_m.group(1).strip() if summary_m else text[:600].strip()
    follow_m = FOLLOWUP_RE.search(text)
    follow = follow_m.group(1).strip() if follow_m else ""
    return summary, follow


def main():
    secrets = _load_secrets()
    if secrets.get("BILLETKIT_FELIX_DISABLED", "").lower() == "true":
        _logmsg("disabled via secret")
        return

    started = time.time()
    fire_id = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S")
    _logmsg(f"=== felix fire {fire_id} ===")

    try:
        from mcp_router import MCPRouter, default_billetkit_servers
    except Exception as e:
        _logmsg(f"router import failed: {e}")
        return

    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY", "")
    use_proxy = bool(master_key) and secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "sonnet" if use_proxy else "claude-sonnet-4-5"

    _logmsg("booting mcp router...")
    router = MCPRouter(default_billetkit_servers(secrets))
    try:
        router.wait_until_ready(timeout=120)
        inv = router.tool_inventory()
        tool_count = sum(len(t) for t in inv.values())
        _logmsg(f"router up: {tool_count} tools across {len(inv)} servers")

        tools = router.as_anthropic_tools()
        # Build user message with history + operator messages
        user_msg = (
            f"## your last 12 fires (oldest first)\n\n{_recent_actions(12)}\n\n"
            f"## recent operator messages (last 24h)\n\n{_recent_operator_messages(24)}\n\n"
            f"now pick the highest-EV action and execute it. end with <action_summary> and optional <follow_up>."
        )

        messages = [{"role": "user", "content": user_msg}]
        final_text = None
        WRAP_UP_AT_TURN = 18  # inject "wrap up" pressure after 18 tool turns
        MAX_TURNS = 30

        for turn in range(MAX_TURNS + 1):
            # Inject wrap-up pressure if we're getting near max turns
            if turn == WRAP_UP_AT_TURN:
                remaining = MAX_TURNS - turn
                messages.append({"role": "user", "content": [{
                    "type": "text",
                    "text": (
                        f"REMINDER: you have {remaining} tool turns left before the fire ends. "
                        f"If you have something to ship, ship it and write your <action_summary> NOW. "
                        f"If you're still exploring, STOP exploring and commit to ONE concrete action. "
                        f"Better to ship a small thing than to hit max-turns with no summary."
                    ),
                }]})
            try:
                r = requests.post(endpoint, json={
                    "model": model,
                    "max_tokens": 3000,
                    "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                    "tools": tools,
                    "messages": messages,
                }, headers={
                    "x-api-key": auth_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }, timeout=240)
                r.raise_for_status()
            except Exception as e:
                _logmsg(f"  ! API call failed at turn {turn}: {e}")
                break

            resp = r.json()
            content = resp.get("content", [])
            stop = resp.get("stop_reason")

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses or stop != "tool_use":
                final_text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                break

            messages.append({"role": "assistant", "content": content})
            tool_results = []
            for u in tool_uses:
                name = u["name"]
                args = u.get("input", {}) or {}
                # Block Stripe writes hard
                if name.startswith("stripe__") and any(name.endswith(x) for x in (
                    "__create_refund", "__cancel_subscription", "__update_subscription",
                    "__create_customer", "__create_product", "__create_price",
                    "__create_payment_link", "__create_invoice", "__create_invoice_item",
                    "__create_coupon", "__update_dispute", "__stripe_api_execute",
                )):
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": u["id"],
                        "content": "BLOCKED: stripe writes require explicit operator approval in chat. propose the action to the operator via outbox instead.",
                        "is_error": True,
                    })
                    continue
                tr = router.call_tool(name, args, timeout=90)
                _logmsg(f"  tool: {name}({json.dumps(args)[:120]}) → ok={tr.get('ok')} chars={len(tr.get('content','') or '')}")
                tool_results.append({
                    "type": "tool_result", "tool_use_id": u["id"],
                    "content": (tr.get("content") or "")[:7000],
                    "is_error": not tr.get("ok", False),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            _logmsg("hit max turns (25)")

        if not final_text:
            final_text = "(no final text produced — likely hit max turns mid-tool-call)"

        summary, follow = extract_summary(final_text)
        _logmsg(f"action_summary: {summary[:300]}")
        if follow:
            _logmsg(f"follow_up: {follow[:300]}")

        # Persist to action log
        entry = {
            "at": _now_iso(),
            "fire_id": fire_id,
            "action_summary": summary,
            "follow_up": follow,
            "wall_seconds": round(time.time() - started, 1),
        }
        ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACTIONS_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        _logmsg(f"=== felix fire {fire_id} done ({entry['wall_seconds']}s) ===")
    finally:
        router.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
