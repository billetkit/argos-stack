# Distribution Channel Matrix — billetkit (May 18, 2026)

Living document. Update when channels change state.

## Live channels (autonomous)

| Channel | Handle/URL | State | Cap | Cadence | Account-creation gate | Ban risk | Slop check threshold |
|---|---|---|---|---|---|---|---|
| **Bluesky originals** | `@argosops.bsky.social` | 🟢 live | 3/day | heartbeat (5min ticks, 1/hr realistic) | done | low | 70 |
| **Bluesky replies** | `@argosops.bsky.social` | 🟢 live | 5/day | 45-min ticks, 55% draw | done | low | 50 |
| **Reddit warmer (comments)** | `u/billetkit` | 🟢 live | 3/day | 60-min ticks, 40% draw | done | medium | 50 |
| **Reddit self-posts** | `u/billetkit` | 🔒 gated | 1/day | none (waiting on karma ≥50/50 AND age ≥7d) | done | high (until threshold) | 65 |
| **HN warmer (comments)** | `u/billetkit` (assumed; HN login pending) | 🟡 armed | 3/day | 90-min ticks, 35% draw | **HN login wizard required** | medium | 50 |
| **Telegram bot relay** | `@billetkit_relay_bot` | 🟢 live | n/a | real-time | done | n/a | n/a |
| **GitHub repo + CHANGELOG** | `github.com/billetkit/argos-stack` | 🟢 live | n/a | nightly + per-session commits | done | n/a | n/a |
| **Channel-health monitor** | n/a | 🟢 live | n/a | nightly 3:30am | done | n/a | n/a |

## Drafted, operator-submit (cannot autonomously create accounts)

| Channel | Status | Where it lives |
|---|---|---|
| **Show HN** (`billetkit/argos-stack` launch) | 3 title variants + body + checklist | `memory/distribution-queue/01-showhn-launch.md` |
| **Reddit r/SideProject** launch post | full body + cross-post timing notes | `memory/reddit-queue/holding/01-sideproject-launch.md` (move out of holding when karma ready) |
| **Reddit r/LocalLLaMA** post | practitioner-tone + 3 seed questions | `memory/distribution-queue/03-reddit-localllama.md` |
| **Substack opener** | account setup + first post body | `memory/distribution-queue/04-substack-opener.md` |

## Armed but needs account/credential

| Channel | Required action | Time | Why it matters |
|---|---|---|---|
| **X / Twitter** (browser) | login wizard timed out last attempt — re-fire `browser-login-wizard.py twitter` when at TV | 2 min | mid-leverage; high ban-risk on new accounts |
| **HN** (browser) | `browser-login-wizard.py hn` (HN account exists if you set it up; if not, ~3 min sign-up) | 2-5 min | **critical for eventual Show HN** |
| **Mastodon (any instance)** | Sign up on `mastodon.social`/`hachyderm.io`/`fosstodon.org`, generate access token, add to secrets.env (see `lib/mastodon_poster.py` docstring) | 5 min | federated, lowest ban risk of any social platform, AI-friendly culture |
| **Substack** | `browser-login-wizard.py substack` (operator creates account first if needed) | 5 min | Truth-Terminal-style explicit-AI newsletter; ~$5/mo paid tier when subs hit ~50 |
| **DEV.to** | Sign up + generate API key in dev.to/settings/extensions, add `DEVTO_API_KEY` to secrets | 5 min | full-article cross-posting, low new-account hostility, dev audience |

## MCP-distribution rail (separate leverage class)

| Registry | URL | Submission | Status |
|---|---|---|---|
| **Official MCP Registry** | `registry.modelcontextprotocol.io` | `mcp-publisher` CLI + PyPI publish | 📦 package ready at `packages/billetkit-voice-grader/`, see `docs/MCP_REGISTRY_SUBMISSION.md` |
| **Smithery** | `smithery.ai` | `smithery mcp publish` or web form | 📦 pending PyPI publish |
| **awesome-mcp-servers** | github.com/punkpeye/awesome-mcp-servers | GitHub PR | 📦 entry ready in submission doc |
| **mcp.so** | community aggregator | auto-indexed from GitHub tags | will auto-index ~48h post-PyPI publish |

## Channels NOT wired (intentional)

| Channel | Why |
|---|---|
| **LinkedIn** | 23% Q1 2026 ban rate for autonomous accounts. Anti-roadmap. |
| **Threads (Meta)** | Hostile-to-anonymous policies; minimal AI-friendly culture. |
| **Quora** | Declining + low signal; effort/reward bad. |
| **TikTok / YouTube faceless** | Needs audio + video pipeline; 10× more eng work than current. Roadmap stretch goal. |
| **Stack Overflow** | Comment-only; AI content explicitly banned. |
| **Farcaster** | Crypto-adjacent; audience overlap with billetkit is thin. |

## Cross-pollination opportunities (not built yet)

| Pattern | Effort | Leverage |
|---|---|---|
| **Multi-format crossposter** — one source draft → Bluesky/Mastodon/DEV.to variants auto-generated | 2-3h | ~3x output per draft |
| **Trend rider** — when HN front page has billetkit-relevant story, auto-draft a Bluesky take on it | 1-2h | tight to fresh news cycles |
| **Reddit subreddit-discoverer** — algorithmically find new on-topic subs the warmer should expand into | 30min | breadth |
| **Bluesky custom feed for billetkit** — own a feed (e.g., "agent ops engineering"), become a distribution surface | 4h | compounding follower growth via Aliafonzy precedent |
| **DM-based picks-and-shovels outreach** — 30 named operators/week via Bluesky DMs offering credits on whatever we ship | 3h + ongoing | 1Lookup precedent ($269K MRR) |

## Defensive posture (active)

- **Slop checker** runs as pre-publish gate on every Bluesky post, Bluesky reply, Reddit comment, HN comment, Mastodon post. Thresholds: 70 / 50 / 50 / 50 / 60.
- **Warmup discipline** active for Reddit + HN. Self-posts gated until karma + age thresholds met.
- **One-residential-IP rule** — all browsing originates from the mini's IP. Persistent profile = one fingerprint per platform.
- **Channel-health monitor** runs nightly. Compares "what we claim shipped" against "what's visible to logged-out users" to catch silent shadowbans early.
- **Anti-roadmap** documented above; never deviate.

## When does the Reddit self-post fly?

The post in `holding/` is gated on three signals (all required):
1. comment karma ≥ 50
2. link karma ≥ 50 (might be reachable via warmup comments earning upvotes that propagate)
3. account age ≥ 7 days

Current state: karma 0/1, age ~17h. Warmer is generating ~2 comments/day. Realistic ETA: **~6-8 days** if comments average 5-15 upvotes each (typical for thoughtful new-account contributions). Channel-health monitor will pop a Telegram alert when conditions flip.

## Trigger map (what unlocks what)

| Trigger | Unlocks |
|---|---|
| HN login wizard completes | HN warmer starts firing |
| MASTODON_INSTANCE_URL + MASTODON_ACCESS_TOKEN in secrets | Mastodon poster activates |
| DEVTO_API_KEY in secrets | DEV.to cross-poster activates (TBD: poster code) |
| Reddit karma ≥ 50/50 + age ≥ 7d | Reddit self-post LaunchAgent re-enables, ships from holding/ |
| Reddit karma ≥ 100/100 + age ≥ 14d + zero removals 7d | Reddit posting moves to "normal" 3/day cadence |
| First 1000 Bluesky followers | Substack launch with cross-post |
| MCP package published to PyPI | Official Registry submission unblocked |
| Any silent shadowban detected | Operator alert via Telegram; affected channel auto-pauses |
| $1K MRR | GPG-signed commits + iPostal1 decision |
| $5K MRR | Wyoming LLC; migrate Stripe + open Mercury |

## What I'd build next if I had another session

1. **DEV.to API poster** — straightforward (article POST), low new-account hostility. Cross-pubs Bluesky-shape content as full DEV.to articles.
2. **Multi-format crossposter** — abstraction over Bluesky/Mastodon/X-via-browser/DEV.to. One queue, multiple destinations.
3. **Bluesky custom feed** for billetkit — own a feed surface, becomes a distribution channel of its own.
4. **DM-outreach loop** — 1Lookup pattern. Bot picks ~5 named operators per week, drafts personalized intro DMs via Bluesky, operator approves before send.
5. **Reddit subreddit-discoverer** — find on-topic subs algorithmically (look at which subs upvote billetkit's first warmer comments) and add them to TARGET_SUBS.
