# PDF — *The 24/7 Autonomous Agent* — outline

**Working title:** *The 24/7 Autonomous Agent — Build an unattended AI business that ships, on a $599 Mac mini, with no Anthropic-quota dependency.*

**Title candidates to A/B test:**
- *The 24/7 Autonomous Agent: A field guide to the stack that actually ships*
- *Unattended AI: Build an autonomous agent business on a $599 Mac mini*
- *The Agent Operator's Manual: From planning purgatory to shipping production*
- *No Cloud, No Quota, No Sleep: The local-LLM autonomous agent stack*

**Audience (sharp definition):**
- Solo founders building OpenClaw / autonomous-agent setups who keep getting stuck in *planning* and can't reach *shipping*
- The 33% of OpenClaw indie hackers who hit $0 in 30 days (per Sonu Yadav benchmark)
- Pseudonymous builders who need anti-doxxing guards built in
- Devs tired of Anthropic-quota anxiety who want a fully local fallback

**Promise (the literal value):**

By the end of this book, you have a working 24/7 autonomous AI agent on a Mac mini that:

1. Runs unattended via launchd + caffeinate
2. Uses local LLMs (no Anthropic dependency, no $400/month subscription)
3. Has pre-publish guards stopping the most expensive failure modes (identity leaks, brand collisions)
4. Has 3 sub-agents organized by *role* not task — support, sales, memory
5. Has a heartbeat that *does real work*, not "status: ok" pings
6. Sells via a verified Stripe Payment Link rail that bypasses marketplace purgatory
7. Engages on Bluesky with a cold-start playbook proven on 2026 platform mechanics

Revenue is left as an exercise — but the stack is on us.

**Price:** $39 — matches *How to Hire an AI*. Both promise the reader a shortcut.

**Length:** 30-40 pages. Felix's PDF is 38 — that's the target.

**Free chapter for distribution:** Chapter 1 (Stack Overview) on the billetkit.com landing page + as the Bluesky teaser thread + as the Show HN body.

## Chapter list

### 1. The Stack Overview
The whole picture. Architecture diagram, parts list, why each piece. What you'll have when you finish the book.
*Free chapter — used as Bluesky/HN teaser.*

### 2. The 24/7 Setup
- Mac mini as the host. Why $599 is the right floor.
- `caffeinate -dimsu` as a LaunchDaemon (full plist)
- `OLLAMA_KEEP_ALIVE=30s` to prevent the 21 GB RAM hog you'll otherwise create
- Remote Login + SSH key-based access from your laptop
- Headless setup limitations and the keyboard trick (1Keyboard, accessibility keyboard fallbacks)

### 3. The Heartbeat Pattern
- Why your agent's heartbeat should be *mostly pure code, not LLM*
- The "check 5 surfaces, only call LLM if work found" pattern
- Full Python source (annotated)
- The launchd plist (verbatim)
- Why 15 min is the right cadence — not 1 min, not 30 min

### 4. Pre-Publish Anonymity Guards
- The real story: 224 customer-facing files leaked identifiers before this guard existed (sidebar)
- `check-name-leak.sh` — config-driven regex sweep, CI fail-closed
- `check-brand-clash.sh` — catches false-attribution to known brands
- Both scripts verbatim, MIT licensed
- CI integration recipes (GitHub Actions, simple bash)

### 5. Deterministic LLM Wrappers
- Why llama 3.1 8B can't chain 5 tool calls (and 32B can, but the wrapper still matters)
- The "one content-gen call, everything else is code" pattern
- `process-reply-queue.py` as worked example (annotated, full source)
- Voice-check regex catalog (AI tells, hashtag patterns, signature artifacts)
- The retry-with-different-temperature trick

### 6. Role-Based Sub-Agents
- Why "Iris/Remy/Devin/Teagan/Scout" (task-type split) doesn't compound
- Why "support/sales/memory" (role split) does
- Each agent: AGENT.md spec, authority gates, escalation rules
- The nightly consolidation pattern (Felix's actual secret)

### 7. The Bluesky 2026 Cold-Start Playbook
- Why argosops (and your account too, if you start wrong) hits 0 followers
- Week 1: replies-only. 50 follows. Custom feeds. No posts.
- Week 2: 3 posts/week. The 60/30/10 mix (educational / conversational / promotional)
- Starter packs as discovery vectors (the biggest miss for 2026 builders)
- The exact post register that converts (Sam Rose / Patio11 / Pieter Levels — concrete observations, no copywriting hooks)

### 8. The Pivot Framework
- Daily KPI: did a stranger pay $1?
- 30-day product-pivot trigger
- 60-day channel-pivot trigger
- The Felix data: 67% earn revenue, 34% hit $1K+, 33% hit $0. What separates the cohorts.

## Appendices

- **A. The 14-day diary** — chronological log of what v1 actually did. Reframed as case studies for the chapters' techniques.
- **B. Every script in the book, MIT licensed** — `cp` your way to the same stack
- **C. The exact prompts** for each sub-agent
- **D. The reader's 30-day implementation checklist** — day-by-day what to build

## Production notes

- Voice: first-person, observational, technical. Sam Rose / Patio11 register. No marketing hype. No "10x your agent" copy.
- Every chapter: 1-2 code blocks, 1 architecture diagram or screenshot, 1-2 numbered lessons
- Failure stories appear as *sidebars*, never as the main flow
- Tight: 4K words per chapter average → 32K total → ~30 pages at standard PDF density
- Cover image: the architecture diagram from Chapter 1, rendered cleanly
- Trim: ruthlessly. Felix's PDF doesn't have filler; ours can't either.

## Production timeline

- **Tonight:** chapter 1 rewrite (stack overview, ~1500 words)
- **Day 2-3:** chapters 2-4 (24/7 setup, heartbeat, anonymity guards)
- **Day 4-5:** chapters 5-7 (LLM wrappers, sub-agents, Bluesky playbook)
- **Day 6:** chapter 8 + appendices, architecture diagram, edit pass
- **Day 7:** render PDF, build billetkit.com landing page, wire Stripe Payment Link
- **Day 7-10:** Bluesky cold-start as billetkit (replies only)
- **Day 10:** Show HN launch when chapter 1 hook is tight

## The reframe in one line

We're not selling *what happened*. We're selling *what to do*. The 14 days of failure are the *receipt that we know what we're talking about* — not the product.
