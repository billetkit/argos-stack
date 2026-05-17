# MORNING CHECKLIST — 2026-05-17 (Path B)

Read this when you wake up. Total time: ~50 minutes.

## TL;DR

Plan pivoted to **Path B: distribution-first**. PDF parked. Strategy is:
- Drop the v2 stack as a public GitHub repo (the attention magnet)
- @billetkit on **X** is the primary channel (reply-guy + build-in-public)
- Reddit karma runway starts week 1
- Show HN the repo around day 7-10
- PDF becomes the harvest at month 2+, sold to the email list captured by OSS launch

**Open the dashboard first** to see what the mini's doing: **http://192.168.7.103:8080** from any browser on your network. (Or `http://argos-host:8080` if your laptop resolves the alias.)

## Step 1 — ProtonMail (5 min)

1. https://account.proton.me/signup
2. Username: **billetkit** → @proton.me
3. Skip recovery email + phone verification
4. Log out

## Step 2 — X / Twitter signup (8 min) ⬅ NEW: priority 1

1. https://x.com/i/flow/signup
2. Email: **billetkit@proton.me**
3. Display name: `billetkit`
4. Username: **@billetkit** (verify available)
5. Bio:
   > *24/7 autonomous AI agent stack · Mac mini · local LLM · no Claude dependency · open source*
6. Banner / avatar: skip for now, I'll generate later in the week
7. **Don't follow anyone yet.** I'll queue a strategic follow list for day 2.

## Step 3 — GitHub account + create `argos-stack` repo (10 min) ⬅ NEW

1. https://github.com/signup
2. Username: **billetkit**
3. Email: **billetkit@proton.me**
4. Skip the survey + plan-selection prompts
5. Create new repo: **`argos-stack`** (public, MIT license)
6. Description: *24/7 autonomous AI agent stack — Mac mini · local LLM · pre-publish guards · role-based sub-agents.*
7. Don't push anything yet — I push tonight's v2 tree (anonymized) into the repo once you create it. Tell me when it exists.

## Step 4 — Reddit account (5 min) ⬅ NEW

1. https://reddit.com/register
2. Username: **billetkit**
3. Email: billetkit@proton.me
4. Subscribe to: r/SideProject, r/LocalLLaMA, r/openclaw, r/MacApps, r/Entrepreneur
5. **Do NOT post anything.** Karma runway starts with comments only.

## Step 5 — ClawMart seller signup (10 min)

1. https://clawmart.com/sell
2. Email: billetkit@proton.me, display name: billetkit
3. Payout: Stripe Connect (uses your verified Stripe account)
4. Tax: individual / sole prop
5. **Don't list skills yet.** We list `stripe-payment-link-smoke` once the GitHub repo has 50+ stars (credentialing first).

## Step 6 — Domain (15 min)

1. Namecheap, buy **billetkit.com** (~$12/yr)
2. WHOIS privacy: ON
3. Don't wire DNS yet — I do that after Show HN week

## Step 7 — Wire app passwords into the mini (3 min)

After creating X / Bluesky accounts and any app passwords, SSH in and add to `~/.openclaw/secrets.env`:

```
export ARGOS_V2_X_HANDLE="@billetkit"
export ARGOS_V2_X_PASSWORD="..."  # or auth token if API access
export ARGOS_V2_BSKY_HANDLE="billetkit.bsky.social"
export ARGOS_V2_BSKY_APP_PASSWORD="..."
```

X API access is harder than Bluesky's — we may need to use a browser-based posting approach (openclaw browser MCP) instead of API. I'll figure that out tomorrow once the account exists.

## Step 8 — Ping me

Reply: **"accounts done."** I take over:

- Push v2 tree (anonymized) to billetkit/argos-stack
- Polish the README into a chapter-1-style stack overview with the architecture diagram
- Queue 30 X accounts for reply-guy strategy (AI / agent / OpenClaw influencers)
- Draft the Show HN body for day 7-10 launch
- Wire DNS for billetkit.com once you point me at it
- Start the sales sub-agent drafting first batch of X replies (you approve in the dashboard)

## The dashboard

While you do the signups, **open the dashboard in a browser tab**: http://192.168.7.103:8080

You'll see:
- **HEARTBEAT** — countdown to next tick, ticks today, last result
- **KPI** — did a stranger pay today (NO until first sale)
- **MODEL** — which Ollama model is loaded
- **SURFACES** — what each tick saw across 5 channels (highlighted amber when work appears)
- **SUB-AGENTS** — support / sales / memory status
- **SYSTEM** — uptime, RAM, disk
- **LIVE LOG** — heartbeat output, auto-scrolling
- **DRAFTS** — pending X replies / Reddit comments awaiting your approve / reject

When sales drafts a reply, it appears in the DRAFTS panel with green ▸ APPROVE and red ✕ REJECT buttons. Approve = publishes. Reject = discarded.

## State at the moment you wake up

- Mac mini: 24/7, 3 LaunchAgents running (caffeinate, heartbeat, dashboard)
- SSH passwordless, sub-second
- Ollama: qwen2.5-coder:32b + 32b-fast + deepseek-r1:32b
- v2 tree at ~/argos/ on mini
- Dashboard: live at http://192.168.7.103:8080
- Heartbeat: 15-min cadence, currently idle (correct — no accounts wired yet)
- PLAN.md: Path B locked
- PDF drafts: parked in `v2/docs/drafts/future/`, return at month 2

## What I am NOT doing tonight

- Not signing up for accounts (only you can)
- Not buying the domain (only you can)
- Not pushing to GitHub (need your repo to exist first)
- Not publishing anything to any platform
- Not over-shipping more code (the dashboard is the last build for a while — distribution mode now)

Sleep is honest work. Tomorrow's 50 minutes unlocks the whole loop.
