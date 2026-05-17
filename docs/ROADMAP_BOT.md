# billetkit Bot Roadmap — capabilities to add next

_Last updated 2026-05-17. Lives in the public stack._

## What the bot is today (May 2026)

- Real-time Telegram relay (`@billetkit_relay_bot`) running 24/7 on a Mac mini
- Claude Sonnet 4.5 via Anthropic API (LiteLLM proxy with 1h prompt caching, ~90% hit rate)
- Langfuse traces on every turn
- **62 tools available** (5 native: bash/read_file/write_file/osascript/web_search; 57 MCP: filesystem/fetch/memory/git/apple-events/langfuse)
- Bluesky bot-labeled account for posting (`@argosops.bsky.social`)
- Auto-graded draft pipeline (voice grader with 2026 anti-tell wordlist + structural bans)
- Self-hosted Langfuse, FLUX image gen on MPS, 14 LaunchAgents in autonomy stack
- GitHub legitimacy artifact at `github.com/billetkit/argos-stack` (auto-changelog nightly)

## North star

Autonomous anonymous revenue. **$5K MRR = Wyoming LLC threshold.** Reduce user-in-loop everywhere safety permits. Pseudonymous-friendly rails only (Mercury, Polar.sh for EU, Crossmint for crypto).

---

## Week 1 — finish the MCP layer + close obvious gaps

### Bot-side
- [ ] **Add `web_search` MCP equivalent** — wire Tavily MCP once `TAVILY_API_KEY` lands. Replaces the existing fallback. (~5 min)
- [ ] **Stripe MCP (read-only)** — generate a restricted `rk_*` key with `customers.read,charges.read,payment_links.read,subscriptions.read`. Bot can answer "did anyone pay" without bash-curling Stripe. (~10 min once key exists)
- [ ] **GitHub MCP** — `@github/github-mcp-server` with a fine-grained PAT scoped to billetkit/argos-stack only. Lets the bot read issues + open PRs without bash. (~15 min)
- [ ] **Sentry MCP** — error triage on the proxy/dashboard/bot stack. (~15 min, optional until errors compound)
- [ ] **Bluesky MCP (`cameronrye/atproto-mcp`)** — first-class post/like/repost as tool calls instead of the openclaw-bluesky Python skill. Lets the bot draft+post in a single turn. (~20 min)

### Voice + memory
- [ ] **Wire `memory` MCP into nightly dream** — every dream cycle should `add_observations` the salient facts (operator preferences, decisions made, what worked). The knowledge graph compounds, dreaming becomes searchable. (~30 min)
- [ ] **Voice corpus auto-refresh** — `voice-samples.py` already extracts your writing. Add a step that re-ranks samples by recency × engagement and trims to 300 best. (~20 min)
- [ ] **Pangram + GPTZero post-publish check** — for every shipped Bluesky post, run both detectors. If both >80% AI-prob, mark `voice_negative` in Langfuse and surface in morning digest. (~45 min)

### Infra hygiene
- [ ] **Restart hardening** — when telegram-bot restarts mid-conversation, the in-flight tool_use loop breaks. Add SIGTERM handler that drains pending tool calls. (~30 min)
- [ ] **MCP server health monitor** — heartbeat probes each MCP subprocess; if one is dead, log + auto-respawn. (~45 min)

---

## Month 1 — revenue infrastructure

### Pattern A: picks-and-shovels API for agents (Robby Frank precedent — 1Lookup hit $269K MRR)
- [ ] **Pick the primitive**. Candidates: timezone-from-IP, firmographic enrichment, calendar-availability-windows, URL-safety (PhishTank + community lists), Bluesky handle resolution, Reddit subreddit quality score
- [ ] **Wrap as Stripe-metered MCP server**. The bot ships an MCP server that other agents can install. $0.001-0.01/call. Track via Stripe usage records.
- [ ] **Distribution: DM 30 named operators**. The bot itself drafts personalized intros via Anthropic + reaches out via the Bluesky MCP. Offer $5 credit to try.
- **Trigger:** as soon as the primitive ships. **Target:** $100 MRR in 30 days, $1K MRR in 60.

### Pattern B: sell to AI agents via MCP-first distribution (Postiz precedent — $20K → $88K MRR in 60 days)
- [ ] **Every billetkit skill ships as MCP-installable**. The voice-grader, the auto-changelog, the dream pipeline — each becomes its own MCP server other operators can `npx -y` and use against their own LLM.
- [ ] **Public install instructions** at billetkit.com/mcp/<skill>. README + a one-line install command for Claude Desktop / Cursor / Cline / etc.
- [ ] **Pricing**: free tier (rate-limited via PostgreSQL counter), pro at $19/mo, team at $99/mo. Stripe payment links, no account creation.

### Distribution surfaces (anonymity-friendly)
- [ ] **Bluesky build-in-public**. 3-5 posts/day, 70% replies to high-traffic accounts, 20% original, 10% threads. First-person AI voice (Truth Terminal precedent — accounts get a free pass on human-mimicry detection when they're openly AI).
- [ ] **Reddit (r/SideProject, r/LocalLLaMA, r/SaaS)**. The bot drafts; you approve. Documented operator math: one 14K-view thread = 50-200 email subs.
- [ ] **Show HN with em-dash title format**. Drop on a Tuesday-Wednesday morning Pacific. Bot drafts; you ship.
- [ ] **Substack with explicit-AI voice**. The bot itself authors a weekly "what I'm building" — Truth-Terminal-coded. $5/mo paid tier. 50-500 subs realistic.

---

## Month 2-3 — sub-agents + multi-modal

### Sub-agent specialization
Each runs in its own process, owns a Langfuse session, can be reached via Telegram `/cmd <name> <args>`:

- [ ] **scout** — competitive intel. Scrapes Show HN / Indie Hackers / r/SaaS daily for new AI agent SaaS launches; tags by category; flags ones operating in our space.
- [ ] **sales** — handles inbound. When Stripe fires `payment_intent.succeeded`, sales replies with onboarding + first-week check-in. Drafts only — operator approves.
- [ ] **support** — answers "how do I integrate billetkit's X" — reads from the docs MCP, drafts, escalates if stuck.
- [ ] **memory** — owns the knowledge-graph MCP. Periodically reorganizes the graph: deduplicates entities, promotes recurring observations to attributes.
- [ ] **accountant** — daily Stripe + monthly Mercury check. Flags anything unusual. Drafts the morning digest's revenue section.

### Multi-modal
- [ ] **Voice-in via Whisper**. Telegram `/voice` already accepts voice notes — transcribe locally via `mlx-whisper`, treat as text input.
- [ ] **Voice-out via TTS** — for outbox messages, optional `bark` or `xtts-v2` model. Phone gets an audio reply.
- [ ] **Image-in (vision)** — when operator sends a photo, Anthropic vision describes it; bot can act on the contents (read a whiteboard, see a screenshot's content, identify a UI element).
- [ ] **Faceless TikTok pipeline** — if Pattern A/B revenue stalls, the engine: script (qwen2.5:72b) → voiceover (bark) → captions (whisper) → b-roll (FLUX) → scheduled upload. $5-15K/mo precedent on AI-tools niche. Sell the engine at $99/mo.

### Local model upgrades
- [ ] **Speculative decoding qwen2.5:72b** with qwen2.5:0.5b draft → 1.8-2.3× throughput
- [ ] **Migrate FLUX dev to MLX** → 2.8× speedup, 40% less memory
- [ ] **OLLAMA_KEEP_ALIVE 15m already applied** — confirm via heartbeat

---

## Month 3-6 — defensive ops + identity isolation

### Identity isolation (triggers at revenue)
- [ ] **At first $1**: register DBA for billetkit in home state. ~$50, completes the legal-name disclosure
- [ ] **At $1K MRR**: GPG-signed git commits as `billetkit@proton.me`. iPostal1 virtual mailbox decision (Mercury no longer accepts registered-agent addresses in 2026)
- [ ] **At $5K MRR**: form Wyoming LLC ($185-297/yr total). FinCEN BOI exempt for US-formed entities since March 2025. Migrate Stripe to LLC. Open Mercury.
- [ ] **At $5K MRR + EU customers**: add Polar.sh as MoR rail for VAT compliance without operator-doxx

### Defensive ops
- [ ] **One residential IP, one fingerprint, forever**. Document the mini's IP / fingerprint hash. Any cross-contamination = burn the account
- [ ] **Soft-signal auto-stop**. If Bluesky rate-limits or returns a moderation flag, halt that surface for 24h and ping operator
- [ ] **Behavioral biometrics randomization** — for any browser-automation surface (Playwright MCP, when wired): jitter keystroke cadence ±20-30%, vary mouse trajectories, rotate JA4+ TLS fingerprints
- [ ] **Reads-beat-writes 10:1**. Enforce in code: heartbeat counts writes/hr per platform, halts at 80% of platform thresholds (8 posts/day X, 30 writes/hr Bluesky)
- [ ] **Linkedin = never**. 23% Q1 2026 ban rate for autonomous accounts. Hard-blocked in code

### Quality compounding
- [ ] **DPO fine-tune on edit pairs**. When the operator hand-edits a bot draft, capture (LM draft, operator edit) as DPO pair. At 100+ pairs, run nightly LoRA refresh on Qwen3-8B. 9.5/10 voice quality at 10× cheaper per call than few-shot
- [ ] **DSPy `BootstrapFewShot` on the voice grader** — optimize grader prompt with 50 hand-scored pairs, then bootstrap the generator with grader-as-metric. Continuous quality improvement

---

## Month 6-12 — distribution + leverage

### Agent-to-agent commerce
- [ ] **Publish billetkit's MCP servers to a public registry** (Smithery, mcphq, etc.). Other operator agents can `npx -y @billetkit/<server>` and call our paid endpoints
- [ ] **Inter-agent contracts** — accept inbound MCP calls from other agents with payment auth. Bot can sell timezone-lookups to a competitor's agent at $0.001/call, settle via Stripe Connect
- [ ] **Marketplace participation** — list billetkit skills on the OpenClaw marketplace (when it exists). Sub-agent specialization (sales/support/scout) becomes reusable for other operators

### Niche pivots (if dev-tooling stalls)
The dive-11 list, in operator order of effort vs. revenue:
- **Reddit B2B lead-mining service** — billetkit already has scraping + LLM classification. Sell "qualified Reddit DM-ready leads weekly" at $2-4K/mo. **Path to $20K MRR with 5-7 clients.**
- **Prediction market quant bot SaaS** — tooling not trading: indicators, slippage models, copy-trade dashboards. $99-299/mo. Tools market underbuilt
- **Medical billing prior-auth (PT/OT/chiro)** — $41K MRR solo precedent. $1K/clinic/mo. Sticky contracts. Anonymity-friendly B2B
- **Upwork/Contra AI bidding co-pilot** — lighter GigRadar. $49-199/mo. ToS-safe with human review
- **Faceless TikTok engine** — productized: script + voiceover + captions + scheduled upload + affiliate insertion. $99/mo

### Public artifact compounding
- [ ] **Public dashboard** at billetkit.com showing: revenue (Stripe public counter), Bluesky followers, GitHub stars, MCP installs, post-publish detector scores — the levelsio model
- [ ] **billetkit.com newsletter** — weekly digest of what the bot built, in its own voice. 1-3% free→paid conversion benchmark; 8-10% in AI niche
- [ ] **"Built by an AI" badge** for any product where billetkit is genuinely the operator — community signal of trust

---

## Stretch / R&D (no deadline)

- [ ] **Agent-as-author on Substack** — billetkit publishes its own weekly Substack, $5-15/mo, Truth-Terminal-coded explicit-AI voice. 50-500 subs typical. Sustainable forever
- [ ] **Local vision model** — `MLX-Phi-3-vision` or `MLX-Llama-3.2-vision` on the mini for screenshot understanding without Anthropic API cost
- [ ] **MCP server marketplace participation** — when Anthropic launches a registry (rumored Q3 2026), be in the first cohort
- [ ] **Multi-mini sharding** — when a single mini saturates: spin up a second mini at the operator's location, distribute LaunchAgents (one runs the model serving, one runs the bot loop)
- [ ] **Crypto rail** — Crossmint or similar for crypto-pay customers. Anonymity-preserving payment surface for non-US buyers

---

## Trigger map (what unlocks what)

| Trigger | Unlocks |
|---|---|
| `TAVILY_API_KEY` in secrets | Tavily MCP server (web search upgrade) |
| `STRIPE_RESTRICTED_KEY` in secrets | Stripe MCP server (revenue visibility for the bot) |
| First Bluesky post via the new bot label | Reply-guying loop into 100K+ accounts begins |
| 100+ DPO edit pairs collected | LoRA refresh on Qwen3-8B → 10× cheaper voice calls |
| First $1 sale | DBA registration + Mercury research |
| $1K MRR | iPostal1 decision + GPG-signed commits |
| $5K MRR | **Wyoming LLC + Mercury + LLC-Stripe migration + Polar.sh for EU** |
| $10K MRR | First sub-agent specialization (scout or sales) goes from draft-only to autonomous |
| 1,000 Bluesky followers | Substack launch with explicit-AI voice (~50 initial subs from cross-post) |
| Any Anthropic-detector flag in Langfuse | Auto-halt that surface, switch to "raw agent journal" mode |

---

## Anti-roadmap (what NOT to build)

- **NO LinkedIn**. 23% Q1 2026 ban rate, no exceptions
- **NO X/Twitter posting under the autonomous account**. Reply-only via operator's main account; original posts under the bot account get fingerprint-flagged faster than Bluesky
- **NO sustained romantic/seductive register or apologetic-AI voice** — explicit AI, dry, slightly bitter, never sycophantic
- **NO bypassing CAPTCHAs or bot-detection** — respect the signal, find a different surface
- **NO accounts the operator can't realistically maintain alone** if the bot/laptop dies for a week
- **NO trading or financial transactions** initiated by the bot. Reads only, until explicit operator confirmation each time
- **NO scraping faces or compiling PII** — even of public figures
- **NO premature productization** — wait for 30+ unique operators to use a primitive before charging for it
