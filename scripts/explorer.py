#!/usr/bin/env python3
"""explorer.py — Curiosity-driven exploration. The bot's initiative engine.

Every 2 hours, the explorer boots the full 145-tool MCP router and picks ONE
exploration objective (weighted random). It then uses the full tool surface
to actually investigate the question, writes findings to memory/explorations/,
and adds 3-8 stable observations to the memory MCP knowledge graph.

This is the "strategic curiosity" pattern from the 2026 research on agentic
exploration: identify knowledge gaps, formulate hypotheses, validate via real
tool calls, consolidate findings. Not random wandering — directed novelty
under a fixed budget.

Cost: ~$0.01-0.03 per run via LiteLLM-routed Sonnet. 12 runs/day = $0.12-0.36/day.

Output:
  - memory/explorations/<ts>-<objective>.md  (full report)
  - knowledge graph entries via memory MCP    (persistent observations)
  - operator-outbox notification              (only when finding warrants surfacing)
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

log = logging.getLogger("explorer")

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent
MEMORY = ROOT / "memory"
EXPLORATIONS = MEMORY / "explorations"
LOG_FILE = MEMORY / "explorer.log"
CURIOSITY_SEEDS = MEMORY / "curiosity-seeds"
OUTBOX = MEMORY / "operator-outbox"

EXPLORATIONS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "lib"))


def _ts() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")


def _logmsg(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a").write(f"[{datetime.datetime.now(datetime.UTC).isoformat()}] {msg}\n")
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


# Weighted exploration objectives. Strategic curiosity > random wandering.
OBJECTIVES = [
    (4, "capability-scout", (
        "Find ONE new tool, library, framework, or MCP server released in the last "
        "30 days that billetkit could integrate into its stack. Use tavily__tavily_search "
        "for recent releases. Check github trending. Output: what it is, why it's useful, "
        "exact install command, what billetkit subsystem it'd plug into. Then add 3 stable "
        "facts about it to the knowledge graph via memory__create_entities + observations."
    )),
    (3, "competitive-intel", (
        "Find ONE new autonomous-AI-agent product/SaaS launched in the last 14 days. "
        "Use tavily__tavily_search for 'autonomous AI agent launch' + extract key URLs. "
        "Understand: what does it do, who's the operator, what's the pricing model, "
        "what's their distribution play. Output a 200-word competitive brief. Add the "
        "product as an entity in memory MCP with key observations."
    )),
    (3, "knowledge-gap-fill", (
        "Read the current knowledge graph (memory__read_graph). Identify ONE topic where "
        "billetkit has thin context (few/no observations). Use tavily + fetch to research "
        "it. Add 5-8 fresh observations to that entity in memory. Topic candidates: voice "
        "detectors, MCP protocol updates, Bluesky algorithm changes, Reddit AutoMod rules, "
        "anthropic API changes, mlx vs ollama benchmarks, local LLM finetuning."
    )),
    (3, "voice-corpus-expand", (
        "Find ONE writer whose voice is excellent and whose register matches billetkit's "
        "(first-person, technical, lowercase, concrete, slightly dry/bitter — patio11, "
        "levelsio, swyx, simonwillison are existing seeds). Use tavily or fetch a recent "
        "blog post/Bluesky thread by them. Extract 3-5 specific voice patterns they use "
        "(sentence rhythm, anti-tell avoidance, structural quirks). Append to memory/voice-corpus-extracted.md."
    )),
    (2, "hypothesis-test", (
        "Generate ONE testable hypothesis about billetkit's distribution. Examples: "
        "'replies to posts with 50-200 likes get 2x engagement of replies to <50 like posts', "
        "'comments in r/IndieHackers convert to profile clicks at 3x the rate of r/SaaS'. "
        "Then propose a concrete 7-day validation experiment: what to track, expected "
        "result, success threshold. Write it as a proposal to operator-outbox so operator "
        "can approve. Add the hypothesis to memory MCP for future reference."
    )),
    (3, "self-audit", (
        "Read recent billetkit activity logs (heartbeat, scout, warmer, replies — last 24h). "
        "Identify ONE specific pattern that could be improved: a script that errors often, "
        "a draft-type that gets rejected repeatedly, a slop_checker flag that fires too "
        "often, a time-of-day pattern in engagement. Output a 150-word audit note + a "
        "concrete proposed fix. Don't ship the fix yourself — leave that for the operator."
    )),
    (3, "trend-rider", (
        "Pull top stories from HN + Reddit r/LocalLLaMA + r/MachineLearning in the last "
        "24h via fetch + reddit APIs. Identify ONE story trending that billetkit has "
        "genuine technical context on. Draft a 200-280 char Bluesky take that would ride "
        "the conversation. Drop the draft into memory/drafts/<ts>-bluesky-post.md "
        "(the heartbeat will auto-grade + ship if it passes)."
    )),
    (2, "curiosity-seed-followup", (
        "Read memory/curiosity-seeds/ for recent seeds written by the heartbeat. Pick "
        "ONE that's interesting and unexplored. Investigate it using whatever MCP tools "
        "fit. Write findings, move the seed to processed/."
    )),
]


SYSTEM_PROMPT = """You are billetkit's explorer — the autonomous initiative engine. You have one objective per run, a fixed budget of ~10 tool calls, and the full 145-tool MCP surface available.

Mindset: strategic curiosity, not random wandering. Form a hypothesis or specific question first. Use tools to validate or fill the gap. Write findings as concrete claims with sources. Persist what's worth remembering to the knowledge graph via memory__create_entities and memory__add_observations.

Voice rules apply to your output:
- Lowercase first words OK
- Specific numbers, named entities, real URLs
- NO em-dashes (use periods or parens)
- NO anti-tell wordlist words (delve, tapestry, leverage, harness, multifaceted, comprehensive, furthermore, moreover, synergy, foster, holistic, streamline, elevate, empower, paradigm, navigate the complexities)
- No exclamation points
- Be terse. Findings > prose.

After all your tool calls, output a final report inside <report>...</report> tags:

<report>
## <objective_id> · <one-line summary>

### what i found
<2-5 bullet findings, each concrete and sourced>

### why it matters for billetkit
<2-3 sentences, specific impact>

### added to knowledge graph
<list of entity names + key observations you persisted>

### follow-up worth doing
<one concrete next action OR "none">
</report>

OBJECTIVE: {objective_desc}"""


def pick_objective() -> tuple[str, str]:
    weighted = []
    for w, oid, desc in OBJECTIVES:
        weighted.extend([(oid, desc)] * w)
    return random.choice(weighted)


REPORT_RE = re.compile(r"<report>([\s\S]*?)</report>", re.IGNORECASE)


def extract_report(text: str) -> str:
    m = REPORT_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def main():
    secrets = _load_secrets()
    if secrets.get("BILLETKIT_EXPLORER_DISABLED", "").lower() == "true":
        return

    started = time.time()
    _logmsg(f"--- explorer tick ({_ts()}) ---")

    obj_id, obj_desc = pick_objective()
    _logmsg(f"objective: {obj_id}")

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
        system = SYSTEM_PROMPT.replace("{objective_desc}", obj_desc)
        messages = [{"role": "user", "content": "Begin. Use tools as needed. Then output the <report>...</report> block."}]

        final_text = None
        for turn in range(15):  # max 14 tool calls + 1 final (bumped from 11; observed underrun)
            try:
                r = requests.post(endpoint, json={
                    "model": model,
                    "max_tokens": 2048,
                    "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                    "tools": tools,
                    "messages": messages,
                }, headers={
                    "x-api-key": auth_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }, timeout=180)
                r.raise_for_status()
            except Exception as e:
                _logmsg(f"  ! API call failed: {e}")
                return
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
                # Defense: hard-block Stripe writes at this layer (same rule as scout)
                if name.startswith("stripe__") and any(name.endswith(x) for x in (
                    "__create_refund", "__cancel_subscription", "__update_subscription",
                    "__create_customer", "__create_product", "__create_price",
                    "__create_payment_link", "__create_invoice", "__create_invoice_item",
                    "__create_coupon", "__update_dispute", "__stripe_api_execute",
                )):
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": u["id"],
                        "content": "BLOCKED: explorer cannot call Stripe write operations.",
                        "is_error": True,
                    })
                    continue
                # Defense: block GitHub write operations
                if name.startswith("gh__") and any(x in name for x in (
                    "create_issue", "update_issue", "create_pull_request", "merge_pull_request",
                    "create_or_update_file", "delete_file", "push_files",
                )):
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": u["id"],
                        "content": "BLOCKED: explorer is read-only for github.",
                        "is_error": True,
                    })
                    continue
                tr = router.call_tool(name, args, timeout=60)
                _logmsg(f"  tool: {name}({json.dumps(args)[:100]}) → ok={tr.get('ok')} chars={len(tr.get('content','') or '')}")
                tool_results.append({
                    "type": "tool_result", "tool_use_id": u["id"],
                    "content": (tr.get("content") or "")[:6000],
                    "is_error": not tr.get("ok", False),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            _logmsg("hit max turns")

        if not final_text:
            _logmsg("no final text produced")
            return

        report = extract_report(final_text)
        out_path = EXPLORATIONS / f"{_ts()}-{obj_id}.md"
        out_path.write_text(f"# Explorer · {obj_id} · {_ts()}\n\n_Generated by claude-sonnet-4-5 via MCPRouter_\n\n---\n\n{report}\n")
        _logmsg(f"wrote {out_path.name} ({len(report)} chars, {time.time()-started:.1f}s)")

        # Surface trend-rider drafts directly into the bluesky drafts dir (heartbeat auto-grades)
        if obj_id == "trend-rider":
            # try to extract a candidate post from the report
            m = re.search(r"(?:^|\n)([a-z0-9].{60,260})(?:\n|$)", report)
            if m:
                draft_body = m.group(1).strip()
                if 60 <= len(draft_body) <= 280:
                    draft_path = MEMORY / "drafts" / f"{_ts()}-bluesky-post.md"
                    draft_path.parent.mkdir(parents=True, exist_ok=True)
                    draft_path.write_text(
                        f"# Proactive draft · bluesky-post\n\n"
                        f"_Generated by explorer (trend-rider) using claude-sonnet-4-5 + MCP_\n\n"
                        f"---\n\n{draft_body}\n"
                    )
                    _logmsg(f"  → also wrote trend-rider draft: {draft_path.name}")

        # Surface hypothesis-test proposals to operator outbox so they can approve
        if obj_id == "hypothesis-test":
            OUTBOX.mkdir(parents=True, exist_ok=True)
            (OUTBOX / f"{_ts()}-explorer-hypothesis.md").write_text(
                f"explorer proposed a distribution hypothesis worth testing:\n\n{report[:1500]}\n\n"
                f"full: ~/argos/memory/explorations/{out_path.name}\n\n"
                f"reply 'approve' to enable, or 'skip' to ignore."
            )

    finally:
        router.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
