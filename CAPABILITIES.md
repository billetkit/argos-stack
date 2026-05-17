# billetkit · Agent Capabilities Inventory

What I (Argos / billetkit) can actually reach and do, as of 2026-05-17.

This document exists so that I (the agent) and my sub-agents have explicit
self-awareness of the full toolkit. The dream of 2026-05-17 surfaced a
recurring problem — the agent didn't know what tools it had to reach for, so
it defaulted to generic outputs. Knowing what's available is half the work.

---

## 🧠 LANGUAGE MODELS (via LiteLLM proxy at localhost:4000)

| Model | Endpoint Alias | Use When |
|---|---|---|
| Claude Sonnet 4.5 | `sonnet` | Conversational layer, nuanced writing, anything needing real wit. Default for bot replies. |
| Claude Opus 4.7 | `opus` | Deep reasoning, strategic planning, complex multi-step. Reserve — costs 5x Sonnet. |
| Claude Haiku 4.5 | `haiku` | Short classification (auto-grader rubric scoring). 5-25x cheaper than Sonnet. |
| qwen2.5-coder:32b-fast | `qwen-coder-fast` | Local. Heartbeat draft generation. Free. |
| qwen2.5:72b | `qwen-72b` | Local. Heavy reasoning when API budget is tight. Free. ~7 tok/sec. |
| deepseek-r1:32b | `deepseek-r1` | Local. Reasoning specialist with `<think>` blocks. Free. |

All routed through LiteLLM with **$5/day hard cap** + 1h prompt caching. Daily spend reported in Langfuse.

---

## 🎨 IMAGE GENERATION (img-server at localhost:8081)

| Model | Steps | Time | Best For |
|---|---|---|---|
| SDXL Turbo | 4 | ~6s | Fast preview, low quality |
| Playground v2.5 | 30 | ~30-40s | Aesthetic quality, 1024² native |
| SDXL Base 1.0 | 30 | ~30s | Photorealism, vanilla |
| FLUX.1 schnell | 4 | ~30s | Top-tier open-source, no negative-prompt |
| FLUX.1 dev | 20 | ~3-5min | Best quality, hands/faces/composition |

Idle-unload after 10 min of no requests (releases MPS memory back to OS).
Studio UI: http://192.168.7.103:8081
Bot command: `/img <prompt>`

---

## 🔌 INSTALLED SKILLS (clawhub + local)

### Local skills (built by/for this stack)
- `check-name-leak` — anti-doxxing regex scan, fail-closed CI
- `check-brand-clash` — anti-false-attribution scan
- `organic-social-voice` — anti-AI-tell filter for social posts
- `claw-boston-email` — transactional email integration
- `openclaw-bluesky` — atproto wrapper
- `stripe-payment-link-smoke` — funnel verification

### ClawHub skills (vetted via skill-vetting)
- `skill-vetting` — security gate, scans before install (run first on any new skill)
- `capability-evolver-pro` — analyzes own logs, proposes evolutionary improvements
- `agent-browser-clawdbot` — autonomous browser via playwright
- `liang-tavily-search` — web search (TAVILY_API_KEY wired)
- `mem0-memory` — persistent agent memory across sessions
- `audit-log-firewall` — logs + filters every tool call
- `encryptedenergy-uptime` — uptime alerts on service silence
- `openclaw-twitter` — X automation (browser-paced)
- `reddit-write` — Reddit posting
- `reddit-post-lab` — simulates karma-runway risk before submission

### Rejected at the security gate (do not force-install)
- `github-automation` — flagged suspicious
- `openclaw-ops-guardrails` — flagged suspicious

---

## 🛠 BOT TOOLS (via Anthropic API tool_use)

The Telegram bot has these tools wired in `telegram-bot.py`:

| Tool | What | Limits |
|---|---|---|
| `bash` | Run shell commands on the mini | deny-list: rm -rf, sudo, dd, shutdown, fork bombs, curl\|sh |
| `read_file` | Read files | allow-list: `~/argos/`, `~/.openclaw/`, `/tmp/` |
| `write_file` | Write files | allow-list: `~/argos/v2/memory/`, `~/argos/v2/docs/drafts/`, `/tmp/` |
| `osascript` | Run AppleScript (display dialog, notifications, open URLs) | renders to TV |

---

## 📡 EXTERNAL APIS WIRED (keys in secrets.env)

| Service | Auth | Purpose |
|---|---|---|
| Anthropic API | `ANTHROPIC_API_KEY` | Sonnet/Opus/Haiku via LiteLLM |
| Telegram Bot | `BILLETKIT_BOT_TOKEN` + `BILLETKIT_BOT_CHAT_ID` | bot ⇄ phone real-time |
| GitHub (billetkit) | `BILLETKIT_GITHUB_PAT` (fine-grained, argos-stack repo) | self-updating CHANGELOG, dashboard stars surface |
| HuggingFace | `HF_TOKEN` | gated model downloads (FLUX) |
| Tavily Search | `TAVILY_API_KEY` | web research (1000 req/mo free tier) |
| Langfuse | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | trace storage, eval scoring |
| Stripe | `STRIPE_SECRET_KEY` | Payment Link checkout monitoring |

### NOT yet wired (operator action required)
- Bluesky `@billetkit.bsky.social` (account created, no app-password yet)
- X / Twitter `@billetkit` (account exists, no automation creds — browser-only)
- Reddit `billetkit` (account exists, browser-automation path chosen)
- ClawMart seller account
- Circle Agent Stack (crypto wallet) — setup doc in `docs/circle-agent-wallet-setup.md`
- Polar.sh (parallel payment rail for EU buyers)

---

## ⏰ SCHEDULED OVERNIGHT JOBS (LaunchAgents)

| Time (local) | Job | Output |
|---|---|---|
| every 5 min | `heartbeat` | 5-surface scan + auto-grade pending drafts + proactive draft gen |
| every 6 hours | `anthropic-rss` | poll Anthropic news, alert operator on new posts |
| 02:30 | `backup` | snapshot to `~/Backups/argos/`, retain 7 |
| 03:00 | `dream` | nightly reflection + scenarios + creative leap → `memory/dreams/` |
| 03:45 | `voice-samples` | rebuild `voice-samples.txt` from operator's actual writing |
| 04:00 | `auto-changelog` | git log → Haiku summary → commit + push |
| 06:00 | `github-trending` | trending repo brief → Telegram |
| 06:30 | `hn-intel` | top 30 HN, AI/agent filter → Telegram |
| 07:00 | `morning-digest` | operational summary + dream teaser → Telegram |
| 24/7 | `caffeinate` | system daemon, prevents sleep |
| 24/7 | `dashboard` | localhost:8080 (LAN) live SSE dashboard |
| 24/7 | `img-server` | localhost:8081 (LAN) studio + bot API |
| 24/7 | `litellm` | localhost:4000 LLM proxy with $5/day cap |
| 24/7 | `telegram-bot` | real-time operator chat with tool-use |
| boot | `colima` | docker daemon for langfuse stack |

15 active LaunchAgents. All survive reboot via auto-login + KeepAlive flags.

---

## 🐳 DOCKER STACK (via colima)

- `langfuse-langfuse-web` (port 3000) — observability UI
- `langfuse-langfuse-worker` — async trace processing
- `langfuse-postgres` — trace storage
- `langfuse-redis` — queue / cache
- `langfuse-clickhouse` — analytical store for traces
- `langfuse-minio` — object storage for trace blobs

---

## 🧰 SUB-AGENTS (by role, not by task)

Per `sub-agents/<role>/AGENT.md` — these are *role definitions*, not running processes. They get invoked when an inbound message routes to that role.

- `support` — buyer questions, refunds <$50 auto-approve, escalate threats/bugs
- `sales` — Bluesky/X reply drafting, Show HN prep, outbound DMs
- `memory` — nightly 03:30 consolidation, weekly Sunday rollup

---

## 🎯 OPERATIONAL CONTEXT BILLETKIT SHOULD ALWAYS REMEMBER

- **The current plan is Path B (distribution-first).** PDF parked until audience exists. See `PLAN.md`.
- **Operator's daily KPI:** did a stranger pay $1 today? Tracked in `memory/kpi.md`.
- **Voice rules** in `skills/organic-social-voice/SKILL.md`. But the *real* voice anchor is `memory/voice-samples.txt` (built nightly from operator's actual writing).
- **The dashboard at http://192.168.7.103:8080** has a presence orb that reflects state (green=idle, cyan=thinking, amber=work pending, pink=drafts ready).
- **Auto-grader rejects ~95% of qwen-generated drafts.** That's a known pattern, surfaced in the 2026-05-17 dream. Solution-in-progress: voice-samples.txt training data instead of style rules.

---

## 🚫 WHAT BILLETKIT CANNOT DO

- Create new accounts (Telegram bot signups, Stripe, banking — operator only)
- Make financial transactions / move money / authorize payments
- Modify scripts, configs, LaunchAgents from the Telegram channel (laptop Claude Code session required)
- Sudo anything
- Post to platforms without bot-side approval gates
- Generate real-person deepfakes (image gen)

---

## 📚 WHERE TO LOOK NEXT

When the agent is uncertain what tool to reach for, read in this order:
1. This file (`CAPABILITIES.md`) — what's installed
2. `PLAN.md` — what we're trying to do
3. `memory/dreams/YYYY-MM-DD.md` — what I figured out last night
4. `memory/voice-samples.txt` — what the operator actually sounds like
5. `skills/<skill-name>/SKILL.md` — how to use a specific skill
6. `sub-agents/<role>/AGENT.md` — what a sub-agent is allowed to do

If the answer isn't in any of those, the right move is usually: ask the operator via Telegram, or queue an intent in `memory/intents/` and wait for the next Claude Code session.
