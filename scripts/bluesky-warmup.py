#!/usr/bin/env python3
"""bluesky-warmup.py — Execute the AT Protocol cold-start playbook for argosops.

Per 2026 Bluesky growth research: brand-new accounts that go straight to
posting promotional content get algorithmically ignored. The accounts that
actually grow follow a 'replies + follows + custom feeds first' pattern for
the first week.

This script does the mechanical pieces:
1. Follow N curated accounts in the dev/AI/indie-hacker niche
2. Subscribe to relevant custom feeds
3. Pull recent posts from those follows for the engagement-watcher to draft replies on

Usage:
    python3 scripts/bluesky-warmup.py --follow 50         # follow up to 50 accounts
    python3 scripts/bluesky-warmup.py --pull-engagement   # find posts to reply to
    python3 scripts/bluesky-warmup.py --status            # show current state
"""
import os, sys, json, pathlib, argparse, datetime
from atproto import Client

ROOT = pathlib.Path("/Users/vydaboss/argos")

# Curated handles in our niche. Quality > quantity. These are real Bluesky devs
# who post about LLMs, agents, AI tooling, infrastructure. Argos can follow them
# without looking spammy — they're public figures who tolerate follows from new
# accounts.
SEED_FOLLOWS = [
    "samwho.dev",                    # security-tier devs
    "danabra.mov",                   # AI infra commentator
    "simonwillison.net",             # high-signal LLM coverage
    "swyx.io",                       # AI engineer thought leader
    "shawn.dev",                     # indie + AI
    "vicki.pet",                     # SRE/observability
    "jvns.ca",                       # Julia Evans, systems
    "alex.payne.co",                 # tech-policy + infra
    "0xabad1dea.bsky.social",        # security
    "thingskatedid.com",             # design + dev
    "molly.wiki",                    # AI critique
    "andrejkarpathy.bsky.social",    # ML foundational
    "wesbos.com",                    # JS dev
    "kentcdodds.com",                # JS / React
    "danabra.mov",                   # dup, fine
    "max-fun.bsky.social",           # game dev / fun
    "ourmaninthenorth.bsky.social",  # tech writing
    "darkpatterns.org",              # UX
    "developerctp.bsky.social",      # dev advocate
    "pcarleton.bsky.social",         # devops
    "alexcooper.bsky.social",        # security
    "patio11.bsky.social",           # Patrick McKenzie
    "marc.info",                     # systems
    "rachelbythebay.bsky.social",    # SRE writing
    "thomasptacek.com",              # security analysis
    "fasterthanlime.bsky.social",    # Rust + systems
    "matklad.bsky.social",           # Rust tooling
    "carlosgaldino.bsky.social",     # dev
    "noahsark.bsky.social",          # security
    "philip.greenspun.com",          # OG
    "krohn.dev",                     # AI tooling
    "yosefk.com",                    # graphics
    "antirez.bsky.social",           # Redis author
    "joelonsoftware.com",            # legendary
    "mattmight.bsky.social",         # research → product
    "joshwcomeau.com",               # CSS/JS
    "rauchg.com",                    # Vercel CEO
    "leerob.io",                     # next.js
    "shadcn.bsky.social",            # design
    "addyosmani.com",                # web perf
    "jasonyaffe.bsky.social",        # indie hacker
    "pavi.bsky.social",              # indie dev
    "petekeen.bsky.social",          # indie + tech
    "joshtaylor.bsky.social",        # indie
    "natfriedman.bsky.social",       # former GitHub CEO
    "stripe.bsky.social",            # payments
    "hashicorp.bsky.social",         # devops
    "anthropic.bsky.social",         # AI lab
    "mistral.ai.bsky.social",        # AI lab
    "huggingface.bsky.social",       # AI hub
]

def load_secrets():
    env = (pathlib.Path.home() / ".openclaw" / "secrets.env").read_text()
    out = {}
    for line in env.splitlines():
        line = line.strip()
        if line.startswith("export "): line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"').strip("'")
    return out

def client():
    s = load_secrets()
    c = Client()
    c.login(s["BSKY_HANDLE"], s["BSKY_APP_PASSWORD"])
    return c

def follow_seed(c, limit=50):
    """Follow curated accounts; skip if already followed."""
    state_file = ROOT / "memory" / "bluesky-warmup-state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"followed": []}
    followed = set(state["followed"])
    new_count = 0
    for handle in SEED_FOLLOWS:
        if new_count >= limit: break
        if handle in followed:
            continue
        try:
            profile = c.get_profile(actor=handle)
            if not profile.viewer.following:
                c.follow(profile.did)
                followed.add(handle)
                new_count += 1
                print(f"  ✓ followed {handle}")
            else:
                followed.add(handle)  # track that it's known
        except Exception as e:
            print(f"  ✗ {handle}: {str(e)[:80]}")
    state["followed"] = sorted(followed)
    state["last_follow_run"] = datetime.datetime.utcnow().isoformat() + "Z"
    state_file.write_text(json.dumps(state, indent=2))
    print(f"\nFollowed {new_count} new accounts (total tracked: {len(followed)})")
    return new_count

def pull_engagement_targets(c, max_targets=15):
    """For each followed account, pull their latest 1-2 posts, queue the most
    repliable ones to memory/reply-queue/ for the engagement-watcher cron to
    draft replies on. The watcher already handles publishing."""
    state_file = ROOT / "memory" / "bluesky-warmup-state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"followed": []}
    seen_file = ROOT / "memory" / "bluesky-engagement-seen.json"
    seen = json.loads(seen_file.read_text()) if seen_file.exists() else []
    seen_set = set(seen)

    queue_dir = ROOT / "memory" / "reply-queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    queued = 0
    for handle in state.get("followed", [])[:20]:  # sample first 20
        if queued >= max_targets: break
        try:
            feed = c.get_author_feed(actor=handle, limit=3)
            for item in feed.feed:
                post = item.post
                if post.uri in seen_set: continue
                seen_set.add(post.uri)
                # Score postability: prefer short, tech-topic, recent
                text = post.record.text
                if len(text) < 40 or len(text) > 400: continue
                # Avoid retweets / hot political
                if any(kw in text.lower() for kw in ["trump", "biden", "israel", "gaza", "vote", "drag", "trans ", "abortion", "racis", "fascis", "nazi", "republican", "democrat", "election", "lgbtq", "defamat", "lawsuit"]): continue
                # Save to reply-queue for the engagement-watcher to draft + publish
                qfile = queue_dir / f"reach-{handle.replace('.','_')}-{post.uri.split('/')[-1]}.md"
                qfile.write_text(f"""# Engagement target — reach out to a followee

**Target:** {handle}
**Post URI:** {post.uri}
**Post CID:** {post.cid}
**Post text:**
{text}

## Action for next heartbeat
Draft a substantive technical reply per skills/organic-social-voice/SKILL.md. The reply rules:
- Add value (data point, contrarian-but-civil, specific experience). Not "great post!".
- ≤ 250 chars (replies have more room than original posts but stay tight).
- No felixops link. No product mention. Pure engagement.
- Reply pattern: `bash scripts/bluesky-publish.sh "<text>" --reply-to-uri {post.uri} --reply-to-cid {post.cid}`

After publishing, move this file to memory/reply-queue/done/.
""")
                queued += 1
                print(f"  → queued reply target for @{handle}")
        except Exception as e:
            print(f"  ✗ {handle}: {str(e)[:80]}")

    seen_file.write_text(json.dumps(sorted(seen_set), indent=2))
    print(f"\nQueued {queued} engagement targets to memory/reply-queue/")
    return queued

def status(c):
    """Print current warm-up state."""
    profile = c.get_profile(actor=os.environ.get("BSKY_HANDLE","argosops.bsky.social"))
    print(f"  followers: {profile.followers_count}")
    print(f"  following: {profile.follows_count}")
    print(f"  posts:     {profile.posts_count}")
    state_file = ROOT / "memory" / "bluesky-warmup-state.json"
    if state_file.exists():
        s = json.loads(state_file.read_text())
        print(f"  warm-up tracked: {len(s.get('followed',[]))} accounts")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--follow", type=int, default=0, help="Follow N seeds (0 = skip)")
    ap.add_argument("--pull-engagement", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    set_secrets = load_secrets()
    os.environ.update(set_secrets)
    c = client()

    if args.status:
        status(c)
    if args.follow > 0:
        follow_seed(c, args.follow)
    if args.pull_engagement:
        pull_engagement_targets(c)
    if not (args.follow or args.pull_engagement or args.status):
        # Default: status + follow 10 + pull 5
        status(c)
        print("\n→ Follow 10:")
        follow_seed(c, 10)
        print("\n→ Pull engagement:")
        pull_engagement_targets(c, 5)
