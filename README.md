# argos-stack

A 24/7 autonomous AI agent stack running on a Mac mini. Pseudonymous operator, MIT licensed, no Anthropic dependency required (local Ollama fallback works).

This repo is **what's actually running on a real Mac mini right now**, not a demo. The agent it powers is [@argosops on Bluesky](https://bsky.app/profile/argosops.bsky.social), publishes its own [CHANGELOG.md](./CHANGELOG.md) every night, and is referred to internally as `billetkit`.

## What's wired (May 2026)

- **Claude Sonnet 4.5** via LiteLLM proxy with 1-hour prompt caching (~90% hit rate, ~10× cost reduction on chatty turns). Local Ollama (`qwen2.5-coder:32b-fast`, `deepseek-r1:32b`) as the cheap-draft fallback.
- **93 MCP tools across 8 stdio servers** via `lib/mcp_router.py`:
  - `fs` — sandboxed filesystem (14 tools)
  - `fetch` — HTTP GET + markdown extraction (1)
  - `memory` — persistent knowledge graph (9)
  - `git` — repo ops (12)
  - `apple` — native macOS via EventKit: contacts, notes, messages, mail, reminders, calendar, maps (7)
  - `langfuse` — self-hosted trace + dataset analysis (14)
  - `tavily` — live web search with markdown extraction (5)
  - `stripe` — live account access with audit logging + two-turn-confirmation rules on writes (31)
- **15 LaunchAgents** for continuous operation:
  - `heartbeat` (5 min) — surface checks, auto-grade drafts, publish to Bluesky if queue has approved content
  - `scout` (1 hr) — MCP-aware proactive worker, weighted across 4 objectives (draft, KG update, market scan, Stripe pulse)
  - `telegram-bot` (real-time) — phone-to-agent relay with full tool access
  - `dream` (nightly) — canonical OpenClaw memory consolidation
  - `auto-changelog` (nightly) — Haiku-summarized git log → public CHANGELOG.md
  - `voice-samples` (daily) — extracts operator's writing for the few-shot voice corpus
  - plus dashboard, img-server (FLUX dev on MPS), litellm proxy, colima, hn-intel, anthropic-rss, github-trending, morning-digest, backup
- **2026 anti-tell voice grader** at `scripts/heartbeat.py` — rejects drafts that hit a 45+ wordlist (delve, tapestry, leverage, harness, multifaceted, synergy, foster, comprehensive, …), em-dash density >1-per-200-words, three-item parallel lists, sign-offs like "hope this helps", and identity violations (claims to be human, apologizes for being AI).
- **Bluesky autoposter** at `lib/bluesky_publisher.py` — idempotently self-labels the account as `bot` per Bluesky policy, ships from `memory/drafts/approved/` at an 8/day cap, filters by `task_id` so only Bluesky-suitable drafts can auto-ship.

## What it does autonomously

- Posts to Bluesky under the bot-labeled account, ~6-8 posts/day at full cadence.
- Maintains its own public CHANGELOG.md.
- Responds to operator messages on Telegram in real-time with the full tool surface.
- Generates context-aware drafts via `scout` (~$0.005/run × 24/day = ~$0.12/day in Claude tokens).
- Consolidates daily memory into the knowledge graph nightly.

## Install one piece (the MCP router)

The 93-tool router is the most reusable component. To wire it into your own bot:

```python
# Boot once at process start
from lib.mcp_router import MCPRouter, default_billetkit_servers

router = MCPRouter(default_billetkit_servers(your_secrets_dict))
router.wait_until_ready(timeout=90)

# Generate Anthropic-compatible tool schema
tools = router.as_anthropic_tools()

# Send tools in your Messages API call. When Claude returns tool_use blocks
# whose name contains "__", dispatch through the router:
result = router.call_tool(block.name, block.input or {})

# On shutdown
router.close()
```

Tool names are namespaced `<serverkey>__<toolname>` so they can't collide. The router boots stdio MCP servers in a daemon thread, exposes a synchronous `call_tool()` so existing `requests`-based code can use it without an async refactor. See `docs/MCP_ROUTER.md` for the full wire-up recipe.

## Architecture

```
                                            ┌────────────────────┐
                                            │  operator's phone  │
                                            └─────────┬──────────┘
                                                      │ Telegram
                                                      ▼
┌──────────────────┐      ┌──────────────────────────────────────────────────┐
│  LaunchAgents    │      │  telegram-bot.py  (real-time relay, 62-93 tools) │
│                  │      └──────────────────────────────────────────────────┘
│  heartbeat 5m ───┼──┐                            ▲
│  scout 1h     ───┼──┤                            │
│  dream nightly   │  │                            │
│  auto-changelog  │  │                            │
│  voice-samples   │  │                            │ tool_use
│  morning-digest  │  ▼                            │
│  backup           │ ┌─────────────────────────────────┐
│  + 8 more         │ │   Claude Sonnet 4.5 (Anthropic) │
└──────────────────┘ │   via LiteLLM proxy (1h cache)  │
                     └─────────────────────────────────┘
                          ▲
                          │ MCP stdio (8 servers)
            ┌─────────────┴─────────────────────────────────────┐
            ▼              ▼          ▼         ▼       ▼       ▼
          fs  fetch  memory  git  apple  langfuse  tavily  stripe
        (14)   (1)    (9)  (12)   (7)    (14)     (5)    (31)
                                          │
                                  ┌───────┴────────┐
                                  │  voice-grader  │  → memory/drafts/approved/
                                  │  (2026 rubric) │
                                  └────────────────┘
                                          │
                                          ▼
                                  ┌───────────────────────┐
                                  │  bluesky_publisher.py │  → @argosops.bsky.social
                                  │  8/day cap, bot label │
                                  └───────────────────────┘
```

## Files worth reading

- `scripts/heartbeat.py` — the 5-min main loop. Surface checks, auto-grade, publish.
- `scripts/scout.py` — hourly MCP-aware proactive worker.
- `scripts/telegram-bot.py` — real-time relay with the 93-tool surface.
- `lib/mcp_router.py` — the synchronous facade over async MCP stdio clients.
- `lib/bluesky_publisher.py` — autoposter with idempotent bot-self-label.
- `skills/openclaw-bluesky/lib/self_label.py` — the canonical Bluesky bot-label helper.
- `docs/ROADMAP_BOT.md` — what gets built next, organized by revenue trigger.
- `docs/MCP_ROUTER.md` — wire-up recipe.
- `CHANGELOG.md` — agent-written nightly digest of what shipped.

## Status

The project is in active development. The agent ships its first autonomous post the same week the autoposter was wired (May 17, 2026). Voice quality is improving as the operator hand-edits drafts and the corpus grows. The full operator roadmap is in `docs/ROADMAP_BOT.md` — anonymous revenue, MCP-first product distribution, Wyoming LLC at $5K MRR.

## License

MIT. Take any piece. The MCP router and the voice grader are the most reusable parts.

## Connect

- Bluesky: [@argosops](https://bsky.app/profile/argosops.bsky.social)
- The CHANGELOG.md updates nightly with what shipped.
