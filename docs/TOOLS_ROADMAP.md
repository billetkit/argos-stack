# billetkit Tool / Capability Roadmap

Living document. Status: 145 tools across 12 MCP servers + 20 LaunchAgents. Updated 2026-05-18.

## What's wired now (the bot's actual capability surface)

| Server | Tools | What it unlocks |
|---|---|---|
| `fs` | 14 | sandboxed file I/O under ~/argos |
| `fetch` | 1 | HTTP GET + markdown extraction (Python uvx) |
| `memory` | 9 | persistent knowledge graph (entities/relations/observations) |
| `git` | 12 | repo ops on /tmp/argos-stack |
| `apple` | 7 | Contacts/Notes/Messages/Mail/Reminders/Calendar/Maps (EventKit) |
| `langfuse` | 14 | self-hosted trace/dataset query |
| `tavily` | 5 | live web search + extract |
| `stripe` | 31 | live Stripe (audit-logged, 2-turn-confirm on writes) |
| `context7` | 2 | version-pinned package docs (NEW — added 2026-05-18) |
| `gh` | 26 | official GitHub MCP — code search, issues, PRs (NEW) |
| `browser` | 23 | Playwright MCP — browser automation as tool_use (NEW) |
| `think` | 1 | sequential-thinking helper (NEW) |
| **Total** | **145** | **Across 12 servers** |

## What the LaunchAgents do (the bot's behaviors)

| Agent | Cadence | Function |
|---|---|---|
| `heartbeat` | 5 min | surface check, auto-grade drafts, publish Bluesky if ready, **drop curiosity seeds (10% chance)** (NEW) |
| `scout` | 1 hr | MCP-aware proactive worker, 4 weighted objectives |
| `explorer` | 2 hr | **NEW — curiosity-driven full-MCP exploration: capability scout, competitive intel, KG gap-fill, voice corpus expand, hypothesis test, self-audit, trend ride, seed follow-up** |
| `reddit-warmer` | 1 hr (40% draw) | comment warmup, 3/day cap |
| `bluesky-replies` | 45 min (55% draw) | replies-loop into high-traffic accounts, 5/day |
| `hn-warmer` | 90 min (35% draw) | HN comment warmup (needs login) |
| `dream` | nightly | OpenClaw memory consolidation |
| `auto-changelog` | nightly | Haiku-summarized git log → public CHANGELOG.md |
| `voice-samples` | daily | extract operator writing for voice corpus |
| `morning-digest` | 7am | daily ops summary |
| `channel-health` | 3:30am | shadowban + silent-drop detector |
| `telegram-bot` | real-time | operator phone relay (145-tool surface) |
| `dashboard` | continuous | http://argos-host:8080 |
| `litellm` | continuous | LLM proxy + budget enforcement |
| `img-server` | continuous | FLUX dev on MPS |
| `colima` | continuous | docker for Langfuse |
| `hn-intel` | scheduled | HN trending tracker |
| `anthropic-rss` | scheduled | API changelog watcher |
| `github-trending` | scheduled | trending repos |
| `backup` | scheduled | snapshots to ~/Backups/argos |

**20 LaunchAgents** running 24/7. 5 added this session.

## Curiosity → Exploration pipeline

This is the user-asked-for "let it explore + take initiative" pattern:

```
heartbeat (every 5 min, idle)
   ↓ 10% chance per idle tick
   ↓ call local Ollama with one of 5 curiosity prompts
   ↓ output: one-line question / hypothesis / observation
   ↓
memory/curiosity-seeds/<ts>-seed.md
   ↓
   ↓ (every 2hr, explorer picks weighted objective)
   ↓ (sometimes picks "curiosity-seed-followup": grabs an unprocessed seed)
   ↓
explorer (full MCP, ~10 tool calls, sonnet)
   ↓
memory/explorations/<ts>-<objective>.md   (operator-readable report)
   +
memory MCP knowledge graph                  (persistent facts)
   +
operator-outbox notification                (only when finding warrants it)
```

5 curiosity-prompt categories the heartbeat rotates through:
1. **"is there an MCP server for X"** — capability discovery
2. **"hypothesis worth testing"** — generates testable claims about distribution
3. **"curious or suspicious thing in current stack"** — self-audit
4. **"tool I should learn about"** — gap identification
5. **"person whose voice I should study"** — voice-corpus expansion

7 explorer objectives (weighted, picked randomly per fire):
1. `capability-scout` (w=4) — find new tool/library/MCP server to integrate
2. `competitive-intel` (w=3) — research new autonomous-agent product
3. `knowledge-gap-fill` (w=3) — fill thin areas of the KG
4. `voice-corpus-expand` (w=3) — find new writer to learn voice from
5. `hypothesis-test` (w=2) — propose a testable distribution experiment
6. `self-audit` (w=3) — find one thing to improve in own stack
7. `trend-rider` (w=3) — find trending HN/Reddit story to draft a take on
8. `curiosity-seed-followup` (w=2) — investigate a seed from heartbeat

Cost: ~$0.01-0.03 per explorer run × 12/day = **$0.12-0.36/day**. Well under the $5/day LiteLLM cap.

## What I'd add next (in priority order)

### Tier 1 — high leverage, ship in next session

1. **DEV.to API poster** — full-article cross-poster. POST /api/articles with `DEVTO_API_KEY`. Less new-account-hostile than Reddit/HN. Dev audience.

2. **Multi-format crossposter** — one source draft → emit Bluesky/Mastodon/X-via-browser/DEV.to variants. Abstraction over the existing posters. Triples output-per-draft.

3. **Self-improvement / reasoning-bank loop** — separate LaunchAgent that nightly reads `drafts/approved/` + `drafts/rejected/`, identifies 5 patterns, writes `memory/voice-learnings.md`. Scout + proactive_work then read this and adjust prompts. **Research dive on 2026 memory consolidation said this is the new standard.**

4. **Memory MCP consolidation pass** — the knowledge graph just accumulates. Add a nightly script that scores observations, prunes stale ones, promotes recurring observations to entity attributes. Prevents the "catastrophic memory growth" failure mode the 2026 memory research flagged.

### Tier 2 — medium leverage, ship in 2-3 sessions

5. **Sentry MCP** — needs Sentry account. Once wired: bot can monitor errors in the stack itself, correlate with recent commits.

6. **Qdrant MCP** (semantic memory) — runs Qdrant in colima/docker, exposes vector search to the bot. Better than knowledge-graph alone for "find similar past situation."

7. **Reddit subreddit-discoverer** — algorithmically find new on-topic subs by looking at which subs upvote billetkit's first warmer comments.

8. **Bluesky custom feed** for billetkit (Aliafonzy precedent) — own a feed surface like "agent ops engineering". Custom feeds drive 30-50K weekly impressions for their creators.

9. **DM-outreach loop** (1Lookup pattern) — bot picks 5 named operators/week, drafts personalized intro DMs via Bluesky, operator approves before send. Documented $269K MRR precedent.

### Tier 3 — research now, build later

10. **ProductHunt launch** — one-shot event. Operator must own the brand page + handle the day-of comments. Bot can prep the launch artifacts (screenshots, taglines, FAQ responses).

11. **Lobsters/Tildes submissions** — small but high-signal tech communities. Same Playwright pattern as HN.

12. **Multi-agent specialization** — split scout into named sub-agents (scout-sales, scout-support, scout-memory, scout-accountant). Each runs in own Langfuse session with persona-specific prompts.

13. **Faceless TikTok/YouTube pipeline** — script (qwen) → voiceover (bark/xtts) → captions (whisper) → b-roll (FLUX) → scheduled upload. $5-15K/mo precedent. ~2 weeks of work.

14. **Vision-in via Anthropic** — when operator sends a photo to Telegram, Claude vision describes it. Already supported by Anthropic API; just needs telegram-bot integration.

15. **Voice-in via Whisper** — `/voice` Telegram messages transcribed via mlx-whisper, treated as text input. ~30min build.

16. **TTS out via bark/xtts-v2** — outbox messages also get an audio version. ~1hr build.

17. **Discord server** — billetkit's own community space. Discord MCP server (`elyxlz/discord-mcp`) for read/write. Account creation is the blocker.

18. **Mastodon poster** — already built (`lib/mastodon_poster.py`), waiting on operator to set up instance + token.

### Tier 4 — researched but not building

19. **LinkedIn** — anti-roadmap (23% Q1 2026 ban rate for autonomous).

20. **X / Twitter** — operator earlier said no API. Browser-based posting is built; the login is the blocker.

21. **Threads (Meta)** — hostile-to-anonymous policies, skip.

22. **Quora** — declining + low signal.

23. **Stack Overflow** — AI-content banned explicitly.

24. **Farcaster** — audience overlap with billetkit is thin.

## Tools/MCP servers worth investigating (the 2026 ecosystem)

These came up in the research dive but aren't urgent yet:

- **Fastio MCP** — 251 tools, cloud storage + semantic search. Heavy.
- **Notion MCP** — org memory. Operator-decision.
- **Slack MCP** — most-installed MCP. Operator decides if billetkit needs a Slack.
- **Linear MCP** — issue tracking. Only if billetkit has a Linear project.
- **DesktopCommander** — safer superset of Filesystem + Bash. Could replace some of fs.
- **Brave Search MCP** — alternative to Tavily.
- **Firecrawl MCP** — JS-rendered scraping. Heavier than fetch.
- **MCP Composer / Agent2Agent** — bot-to-bot MCP networking. Stretch.

## Security posture (still active)

- 30+ CVEs filed against popular MCP servers in early 2026 per the research
- Pin versions where possible (currently using `-y` which always pulls latest — should consider lockfile)
- Vendor-maintained servers preferred (Anthropic-official, Stripe-official, GitHub-official)
- Read-only scopes on every PAT/token (Stripe is the exception, audit-logged)
- Each new MCP server inherits Claude's tool_use guardrails (system-prompt-level rules)

## Cost ceiling

| Item | Daily $ |
|---|---|
| Heartbeat (Haiku grading + curiosity seed): ~12 calls × $0.001 | $0.01 |
| Scout (Sonnet + MCP): 24 calls × $0.005 | $0.12 |
| Explorer (Sonnet + MCP, more tools): 12 calls × $0.02 | $0.24 |
| Telegram bot (Sonnet operator chats): variable | $0.10-1.00 |
| Auto-changelog (Haiku nightly): $0.001 | <$0.01 |
| **Total expected** | **~$0.50-1.50/day** |
| LiteLLM budget cap | $5/day |

Comfortable headroom.

## Most recent change log

- 2026-05-17 evening: distribution sprint (Bluesky autopost + Reddit warmer + slop checker + dashboard fix + MCP router + 8-server stack)
- 2026-05-18 early morning: Browser-based distribution (Reddit + persistent profile + slop gate + HN warmer + Bluesky replies + Mastodon poster + channel-health monitor + billetkit-voice-grader MCP package)
- 2026-05-18 mid: **Tool expansion (this doc)** — Context7 + GitHub + Playwright + sequential-thinking MCPs added (+52 tools); Explorer LaunchAgent with 8 weighted objectives; curiosity-seed pattern in heartbeat idle ticks; 145 total tools across 12 servers, 20 LaunchAgents.
