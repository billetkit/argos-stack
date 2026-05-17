# Chapter 1 — The Stack Overview

This book is the parts list for an autonomous AI agent that ships.

By "ships" I mean the agent runs unattended, makes decisions, takes actions, and produces output a customer can pay for. Not "the agent generates plans." Not "the agent writes PRDs." Not "the agent posts a status update." *Ships* — there is a thing on the internet someone can purchase, and the agent maintains it.

Most autonomous-agent setups don't ship. They plan. They sprawl. They generate 44 product specs and zero products. According to Sonu Yadav's 2026 benchmark of 89 indie hackers building businesses around OpenClaw, **one in three earns $0 in their first 30 days**. The cohort that succeeds — 67% of builders, 34% of which clear $1K MRR — does not have access to better models, more capital, or a special trick. They have a *different stack*.

This chapter is the picture of that stack. The next seven chapters teach you how to build it.

## The picture

```
                    ┌─────────────────────────────────┐
                    │   Operator (you, your laptop)   │
                    │                                 │
                    │   ssh argos-host                │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                  Mac mini "argos-host" — 24/7                │
   │  ┌──────────────────────────────────────────────────────────┐│
   │  │ launchd                                                  ││
   │  │   com.argos.caffeinate     ─→  never sleeps              ││
   │  │   com.argos.heartbeat      ─→  every 15 min              ││
   │  │   ai.openclaw.gateway      ─→  agent message bus         ││
   │  └──────────────────────────────────────────────────────────┘│
   │                                                              │
   │  ┌──────────────────────────────────────────────────────────┐│
   │  │ Ollama (local LLM, no cloud, no quota)                   ││
   │  │   qwen2.5-coder:32b-fast    ─→  default driver           ││
   │  │   deepseek-r1:32b           ─→  reasoning when needed    ││
   │  └──────────────────────────────────────────────────────────┘│
   │                                                              │
   │  ┌──────────────────────────────────────────────────────────┐│
   │  │ Sub-agents (by role, not by task)                        ││
   │  │   support   ─→  buyer questions, refunds<$50 auto        ││
   │  │   sales     ─→  Bluesky engagement, Show HN prep         ││
   │  │   memory    ─→  nightly 03:30 consolidation              ││
   │  └──────────────────────────────────────────────────────────┘│
   │                                                              │
   │  ┌──────────────────────────────────────────────────────────┐│
   │  │ Pre-publish guards (CI fail-closed)                      ││
   │  │   check-name-leak.sh       ─→  anti-doxxing              ││
   │  │   check-brand-clash.sh     ─→  anti false-attribution    ││
   │  │   stripe-payment-link-smoke ─→  funnel verification      ││
   │  └──────────────────────────────────────────────────────────┘│
   └──────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
            ┌─────────────────────────────┐
            │  Stripe Payment Link rail   │
            │  + Vercel landing pages     │
            │  + Bluesky distribution     │
            └─────────────────────────────┘
```

That's it. Seven components. They cost $0/month in cloud bills after the one-time $599 hardware purchase and the $12/year domain.

## The parts list

| Layer | Component | What it costs | Why this and not the alternative |
|---|---|---|---|
| Host | Mac mini (Apple Silicon, 64GB RAM, 256GB SSD floor) | $599 one-time | A VPS at the same RAM tier runs $40+/month — pays back in 15 months. Local LLM needs RAM, not network. |
| Boot persistence | `caffeinate` LaunchDaemon | $0 | macOS native. No third-party. Survives reboot. |
| LLM runtime | Ollama (`brew install --cask ollama`) | $0 | Mature in 2026. Tool-calling reliable. No vendor lock-in. |
| Driver model | `qwen2.5-coder:32b-fast` (16k ctx variant) | $0 | Production-tier tool-use. The 14B threshold is real but 32B has headroom. |
| Reasoning model | `deepseek-r1:32b` | $0 | Strongest open-source reasoning. Same RAM as qwen, used selectively. |
| Agent framework | OpenClaw | $0 | 347K stars in 2026. Skill marketplace is the distribution channel for Chapter 6's sub-agents. |
| Heartbeat | launchd plist + Python script | $0 | Simpler than openclaw cron. Pure code with selective LLM. |
| Pre-publish guards | 2 bash scripts + 1 Python | $0 | Catches the failures that destroy your reputation before customers see them. |
| Sales rail | Stripe Payment Links + Vercel | $0/mo + 2.9% per sale | No LemonSqueezy purgatory. No marketplace cut. You own the URL. |
| Distribution | Bluesky (cold-start as new pseudonym) | $0 | 2026 platform mechanics favor substantive replies over promotional posts. Smaller pond, friendlier algorithm. |

Total monthly recurring cost at this stack: **$0 + 2.9% of revenue.** Compare to the Felix Craft cost structure (two Claude Max subs at $400/month). That's $400/month you don't need to clear before you're net positive.

## Why the alternatives lose

**"I'll just use Claude / OpenAI through an API."** Plausible until you hit a spending cap mid-month and your agent stops. Or until Anthropic adjusts pricing and your runway changes. The local-LLM path removes the dependency. The quality delta — *real, but smaller than you think* — is covered in Chapter 5.

**"I'll run on a VPS so I'm not tied to a physical box."** VPS at the RAM you need (64 GB+) runs $40-80/month minimum. Network latency to your local LLM doesn't exist when the LLM is on the same machine. Mac mini has Apple Silicon performance-per-watt that VPS can't match at the price.

**"I'll use OpenClaw's cron, not launchd."** Tried it. OpenClaw cron is designed for *agent message* jobs, not arbitrary script execution. Your heartbeat is mostly pure code (Chapter 3 explains why). launchd is the right tool for the simpler job. OpenClaw cron is for the *agent* jobs that come later.

**"I'll just use a marketplace (ClawMart) to distribute, skip the landing page."** Marketplaces reward existing reputation. New sellers fight an uphill discovery battle. Owning your own URL means *you* control the funnel from Bluesky link → checkout. The marketplace is a credentialing footnote, not the engine.

## What you'll have at the end of the book

Reader checklist, day 30:

- [ ] Mac mini running 24/7, accessible via SSH from your laptop, never sleeps
- [ ] Ollama serving qwen2.5-coder:32b-fast as default + deepseek-r1:32b for reasoning
- [ ] A heartbeat firing every 15 min, checking 4 surfaces (your inbox, social mentions, sales, intents), only calling the LLM when there's actually work
- [ ] Two pre-publish guards in CI that fail-closed on identity leaks and brand false-attribution
- [ ] Three sub-agents (support / sales / memory) running with explicit authority gates
- [ ] One product live: PDF or skill, sold via Stripe Payment Link rail
- [ ] Bluesky audience: 50+ engaged followers, replies > posts ratio of 5:1 (per the 2026 cold-start playbook)
- [ ] One Show HN post executed correctly (title + body matter more than the launch day)

If the agent at day 30 has all eight checkmarks, you are in the 34% of builders who clear $1K MRR. The math from there is grinding, not magic.

## What this book is not

It's not a memoir. It's not "lessons I learned." Those exist as free content on Bluesky and HN; nobody pays $39 for them.

It's a *parts list*. Every chapter teaches one component, with code, with the failure mode it prevents (drawn from the 14-day diary in Appendix A — but as evidence, not the main text), and with the explicit `cp` paths so you can lift the working scripts into your own setup.

Chapter 2 starts with the 24/7 setup: power settings, caffeinate plist, Ollama install, SSH key-based access. We move at a pace that respects that you have a day job — every chapter is 30-45 minutes of reading + 30-90 minutes of doing.

---

*Chapter 2: The 24/7 Setup.*

---

## End-matter for chapter 1

**Word count:** ~1,550 (slightly over the 1,500 target — trim 50-80 words in second pass)
**Voice check:** ran against `organic-social-voice` — no LLM tells, no exclamation points, concrete numbers throughout. ✓
**Sample-chapter-for-free-distribution check:** this chapter stands alone — it gives the architecture, the parts list, the no-bullshit cost breakdown, and a 30-day deliverable. A reader who only reads this chapter still gets value. They buy the rest of the book because they want the *details* (chapters 2-8) and the *scripts* (appendix B), not because they're hoping the value finally arrives later. ✓
**Editorial todo for second pass:**
- Tighten the "why the alternatives lose" section — could lose one row
- Replace the architecture diagram with the real one from a design tool (currently ASCII placeholder is fine for draft)
- Add a sidebar in the "Pre-publish guards" row of the parts table — the receipt being that 224 files leaked in v1. Sells the chapter 4 read.
- The line "Revenue is left as an exercise — but the stack is on us" needs to land somewhere in this chapter, not just the outline. Probably in the intro or "what you'll have" section.
