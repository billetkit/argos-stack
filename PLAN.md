# Argos v2 — Path B: distribution-first

**Pseudonym:** `billetkit` — locked across X / Bluesky / Reddit / GitHub / ClawMart / billetkit.com
**OS account on mini:** `argos` (local-only, never customer-facing)

## The one bet

**Build distribution before product.** No PDF until there is a list. No paid skill launch until there are GitHub stars. The data is unambiguous (research-2026-05-16-distribution.md): every fast-revenue case in 2026 had pre-existing audience. The 33% who hit $0 sprayed product onto void. We are not joining them.

## The play

The v2 stack we built tonight (Mac mini + Ollama + OpenClaw + pre-publish guards + role-based sub-agents + heartbeat) becomes the *attention magnet*, open-sourced on GitHub as `billetkit/argos-stack`. The PDF is the *harvest*, written month 2+ when there are people to sell it to. The paid skill is the *credentialing tool*, listed alongside the OSS repo.

```
   ┌─ Public GitHub repo (OSS, free) ──────────────────────┐
   │  v2 stack: scripts, skills, sub-agents, configs       │
   │  README = the stack-overview chapter, beautifully     │
   │  formatted. MIT licensed. cp-friendly.                │
   └───────────────────────────────────────────────────────┘
                          │
                          ▼ links from
   ┌─ X reply-guy + build-in-public ───────────────────────┐
   │  @billetkit posts daily: what the agent did,          │
   │  receipts of failures, working code snippets.         │
   │  5-10 substantive replies/day to AI/agent accounts.   │
   │  Argos drafts, you approve, posts publish.            │
   └───────────────────────────────────────────────────────┘
                          │
                          ▼ feeds
   ┌─ Reddit (r/SideProject, r/LocalLLaMA, r/openclaw) ────┐
   │  Karma runway starting Day 1. Substantive comments.   │
   │  Week 4-6: launch post for the GitHub repo.           │
   └───────────────────────────────────────────────────────┘
                          │
                          ▼ one-shot
   ┌─ Show HN of the GitHub repo ──────────────────────────┐
   │  "Show HN: I built a 24/7 autonomous AI agent that    │
   │   runs on a $599 Mac mini with no Claude dependency"  │
   │  Free OSS → 10-30K visitors → email captures.         │
   └───────────────────────────────────────────────────────┘
                          │
                          ▼ harvest (month 2+)
   ┌─ $39 PDF + $24 ClawMart skill, sold to the list ──────┐
   │  Email→PDF converts at 3-8% vs cold HN at 0.1-0.5%    │
   │  This is when chapter 1 of the PDF comes back from    │
   │  v2/docs/drafts/future/.                               │
   └───────────────────────────────────────────────────────┘
```

## Distribution loop — daily

- **5-10 X replies** to AI/agent/OpenClaw accounts. Argos drafts via `process-reply-queue.py` pattern, sub-agent `sales` reviews, you approve in dashboard, posts publish.
- **2-3 Reddit comments** in r/SideProject, r/LocalLLaMA, r/openclaw, r/MacApps, r/Entrepreneur. Same draft → review flow.
- **1 X original post** building-in-public style: what the agent did today. Generated nightly by `memory` sub-agent.
- **0 Bluesky activity** week 1 (lower ceiling, save effort). Re-introduce week 3+.

## Sub-agents — role split, distribution-tuned

- **support** — buyer questions, refunds, skill troubleshooting (will activate once any sale exists)
- **sales** — X reply drafting, Reddit comment drafting, build-in-public post composition. Drafts to dashboard for operator approval; publishes on approve.
- **memory** — nightly 03:30 consolidation, weekly Sunday rollup, daily build-in-public post draft

## Daily KPI (two numbers)

1. **Eyeballs delta** — new followers across X / GitHub stars / Reddit karma (sum)
2. **Stranger paid $1?** — yes/no (won't fire for a while; that's fine)

Tracked in `v2/memory/kpi.md` + visualized live in the dashboard.

## Milestones

- **Day 7:** GitHub repo public, README polished, 50+ stars (Show HN week)
- **Day 14:** X 200+ followers, 5K+ impressions on top reply, 100+ GitHub stars
- **Day 30:** 1K X followers, 250 GitHub stars, 50 Reddit karma per sub, email list of 100+ from OSS launch
- **Day 60:** Ship PDF to email list. $1K+ revenue plausible from cohort
- **Day 90:** $500-2K MRR (PDF + skill + GitHub sponsors)

## Pivot triggers

- **Day 7: <50 stars on Show HN** → either Show HN was mistimed or repo README isn't tight. Re-launch in 2 weeks with better hook.
- **Day 30: <300 X followers** → reply strategy isn't landing. Audit which replies got engagement, drop the others.
- **Day 60: $0 revenue** → audience exists but doesn't want product. Survey 20 followers to find out what they DO want.

## Why this beats the previous plans

- v1 (44 products, no audience) → 33%-club outcome confirmed ($0 in 14 days)
- Path A (3 ClawMart skills) → marketplace discovery is gated by reputation we don't have
- Path A-prime (PDF first) → 0.2% cold-HN conversion on $39 = $40-150 expected. Insufficient ROI on 30 pages of writing.
- **Path B (audience-first)** → builds the asset that v1's failure was missing. Every revenue case study supports this. Slowest to first dollar, fastest to *durable* dollar.

## Hard rules (do not violate)

1. **No new code shipped until needed.** The v2 stack is the product. Don't write more.
2. **No PDF writing until 100+ emails captured.** Chapter 1 stays in `drafts/future/`.
3. **No top-level X post that wasn't approved through the dashboard.** Build-in-public character matters. AI tells in the feed = unsubscribe.
4. **No spray. One channel per phase.** Week 1 is X + repo. Reddit karma is background. Bluesky waits.
5. **Daily eyeball KPI is the only metric that matters until $0 → $1.**

## Tech stack additions tonight

- `dashboard.py` — Flask + SSE futuristic UI, accessible at http://argos-host:8080 from any browser on the LAN. Watch agents work in real time.
- `sales/AGENT.md` updated for X reply-guy mode
- X account workflow + the bluesky-warmup.py pattern adapted for X
