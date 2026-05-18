"""bluesky_replies.py — Find high-traffic billetkit-relevant Bluesky posts + draft + post replies.

Reply-guying into 100K+ accounts is the documented 2026 growth lever on Bluesky
(research dive 11). This separates "original posts" (8→3/day cap, slow growth)
from "replies" (much higher cap, much higher visibility per unit work).

Flow per fire:
  1. Pull posts from a fixed set of high-traffic billetkit-relevant accounts
     (configurable via TARGET_HANDLES) within the last 24h
  2. Filter to those with reasonable engagement (some likes/replies already)
     where billetkit has concrete context to add
  3. Ask Haiku to pick the best one + draft a reply
  4. Slop check at threshold 50 (replies are more scrutinized than originals)
  5. Post reply via atproto with proper Strong-Ref reply structure
  6. Log + notify operator

Cap: 5 replies/day (higher than originals because each is lower-risk).
Min gap: 90 min between replies. Quiet hours: 2-7am local.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import random
import re
import sys
import time
from typing import Optional

import requests

log = logging.getLogger("bluesky-replies")

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent  # /Users/argos/argos
MEMORY = ROOT / "memory"
LOG = MEMORY / "bluesky-replies.log"
COUNTER = MEMORY / "bluesky-replies-counter.json"
HISTORY = MEMORY / "bluesky-replies-history.json"
OUTBOX = MEMORY / "operator-outbox"

sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(ROOT / "skills" / "openclaw-bluesky" / "lib"))

# Curated set of billetkit-relevant accounts to reply into. Bias toward technical,
# AI-engineering, indie-SaaS founders, MCP/agent-building. These were selected
# from the research dive on 2026 Bluesky voice references + extended.
TARGET_HANDLES = [
    "pfrazee.com",         # Bluesky team — atproto / MCP-adjacent
    "dholms.xyz",          # Bluesky team
    "patio11.bsky.social", # operator-side tactics
    "swyx.bsky.social",    # AI engineering
    "samwhitmore.bsky.social",
    "aliafonzy.bsky.social",   # custom feeds maintainer, signals reach
    "rahaeli.bsky.social",
    "levelsio.bsky.social",    # solo SaaS pattern (if account exists; may not)
    "danabra.mov",             # AI tools
    "simonwillison.net",       # LLM engineering blog, sometimes posts here
]

MAX_PER_DAY = 5
MIN_HOURS_BETWEEN = 1.5
LOCAL_TZ_QUIET_START_HOUR = 2
LOCAL_TZ_QUIET_END_HOUR = 7
DRAW_PROBABILITY = 0.55   # higher than warmer since cap is higher


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _today_utc() -> str:
    return _now_utc().strftime("%Y-%m-%d")


def _local_hour() -> int:
    return datetime.datetime.now().hour


def _logmsg(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.open("a").write(f"[{_now_utc().isoformat()}] {msg}\n")
    print(msg, flush=True)


def _load_secrets() -> dict:
    p = pathlib.Path.home() / ".openclaw" / "secrets.env"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v.strip().strip('"').strip("'")
    return out


def _load_counter() -> dict:
    if not COUNTER.exists():
        return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_uris": []}
    try:
        d = json.loads(COUNTER.read_text())
        if d.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_uris": d.get("recent_uris", [])[-60:]}
        return d
    except Exception:
        return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_uris": []}


def _save_counter(d: dict) -> None:
    # Cap recent_uris history at last 60 to avoid unbounded growth
    if "recent_uris" in d and len(d["recent_uris"]) > 60:
        d["recent_uris"] = d["recent_uris"][-60:]
    COUNTER.write_text(json.dumps(d))


def _gates_ok(counter: dict) -> tuple[bool, str]:
    if counter["count"] >= MAX_PER_DAY:
        return False, f"cap_reached ({counter['count']}/{MAX_PER_DAY})"
    if counter.get("last_posted_at"):
        delta_h = (time.time() - counter["last_posted_at"]) / 3600
        if delta_h < MIN_HOURS_BETWEEN:
            return False, f"too_soon ({delta_h:.1f}h < {MIN_HOURS_BETWEEN}h)"
    h = _local_hour()
    if LOCAL_TZ_QUIET_START_HOUR <= h < LOCAL_TZ_QUIET_END_HOUR:
        return False, f"quiet_hours ({h:02d}h)"
    if random.random() > DRAW_PROBABILITY:
        return False, "rng_skip"
    return True, "ok"


def _append_history(entry: dict) -> None:
    h = []
    if HISTORY.exists():
        try:
            h = json.loads(HISTORY.read_text())
        except Exception:
            pass
    h.append(entry)
    HISTORY.write_text(json.dumps(h, indent=2))


def _notify_operator(text: str) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = _now_utc().strftime("%Y-%m-%dT%H%M%S")
    p = OUTBOX / f"{ts}-bluesky-reply.md"
    p.write_text(text)


def fetch_recent_posts(client, handle: str, hours: int = 24, max_n: int = 20) -> list:
    """Pull a handle's recent feed via atproto, filter by age + engagement."""
    try:
        resp = client.app.bsky.feed.get_author_feed(params={"actor": handle, "limit": max_n})
        cutoff = time.time() - hours * 3600
        out = []
        for f in resp.feed:
            post = f.post
            rec = post.record
            indexed_at = post.indexed_at
            # parse iso8601
            try:
                ts = datetime.datetime.fromisoformat(indexed_at.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if ts < cutoff:
                continue
            text = getattr(rec, "text", "") or ""
            if len(text) < 30:
                continue
            # Skip replies (we want to reply to ORIGINAL posts, not chain into others' replies)
            if getattr(rec, "reply", None) is not None:
                continue
            out.append({
                "uri": post.uri,
                "cid": post.cid,
                "author_handle": handle,
                "text": text[:600],
                "indexed_at": indexed_at,
                "like_count": getattr(post, "like_count", 0) or 0,
                "reply_count": getattr(post, "reply_count", 0) or 0,
                "repost_count": getattr(post, "repost_count", 0) or 0,
            })
        return out
    except Exception as e:
        _logmsg(f"  fetch error for @{handle}: {type(e).__name__}: {e}")
        return []


DRAFT_PROMPT = """You are billetkit, an explicitly-AI agent on Bluesky (handle @argosops). You're going to write ONE reply to a post from a high-traffic technical/founder account.

Goal: add a SPECIFIC, useful observation that demonstrates you actually read the post + thought about it. NOT generic agreement. NOT a sales pitch. NOT promotional.

Voice rules (strict — Bluesky has lower tolerance for low-effort replies than other platforms):
- Reply length: 60-250 chars. Short, sharp.
- First-person AI framing is OK and ENCOURAGED — billetkit doesn't pretend to be human (Truth Terminal precedent).
- Lowercase first words are fine.
- ONE concrete detail: a specific number, named tool, real URL, file path, or contrarian observation.
- NO em-dashes (use periods or parens for asides).
- NO exclamation points.
- ANTI-TELL WORDS BANNED: delve, tapestry, leverage, harness, utilize, robust, seamless, cutting-edge, multifaceted, synergy, foster, holistic, streamline, elevate, empower, comprehensive, furthermore, moreover, additionally, paradigm, navigate the complexities, unlock the potential, hope this helps, let me know if, happy to chat.
- NO sign-offs.
- NO mentioning billetkit/argos-stack/github repo. NO self-promotion.
- DO NOT say "great post" / "absolutely" / "agreed" without specifics.

Decision: from the candidate posts below, pick the one where billetkit has genuine technical context to add AND where the reply will be visible (mid-engagement is the sweet spot — too low = no audience, too high = drowned).

Return ONLY JSON:
{
  "chosen_uri": "<the at://... uri of the post>",
  "reply": "<the reply body, 60-250 chars>",
  "rationale": "<one sentence: why this post + what your reply adds>"
}

If NONE fit, return: {"chosen_uri": null, "reply": null, "rationale": "no good fit"}"""


def draft_reply(candidates: list, secrets: dict) -> Optional[dict]:
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY", "")
    use_proxy = bool(master_key) and secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "haiku" if use_proxy else "claude-haiku-4-5"

    blob = json.dumps([
        {
            "uri": c["uri"],
            "author": c["author_handle"],
            "text": c["text"],
            "likes": c["like_count"],
            "replies": c["reply_count"],
        }
        for c in candidates
    ], indent=2)

    r = requests.post(endpoint, json={
        "model": model,
        "max_tokens": 500,
        "system": DRAFT_PROMPT,
        "messages": [{"role": "user", "content": f"Candidate posts:\n\n{blob}"}],
    }, headers={
        "x-api-key": auth_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, timeout=30)
    if not r.ok:
        _logmsg(f"draft API error: {r.status_code}")
        return None
    text = r.json()["content"][0]["text"].strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def post_reply(client, parent_uri: str, parent_cid: str, text: str) -> dict:
    """Post a reply with proper Strong-Ref structure (root + parent both point to the post we're replying to)."""
    try:
        from atproto import models
        parent_ref = models.create_strong_ref(
            models.ComAtprotoRepoStrongRef.Main(uri=parent_uri, cid=parent_cid)
        )
        resp = client.send_post(
            text=text,
            reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent_ref, root=parent_ref),
        )
        return {"ok": True, "uri": resp.uri}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main():
    secrets = _load_secrets()
    if secrets.get("BILLETKIT_BSKY_REPLIES_DISABLED", "").lower() == "true":
        return

    counter = _load_counter()
    ok, reason = _gates_ok(counter)
    if not ok:
        if reason.startswith("cap_reached") or reason.startswith("too_soon"):
            _logmsg(f"skip · {reason}")
        return

    _logmsg(f"--- replies tick (cap={counter['count']}/{MAX_PER_DAY}) ---")

    handle = secrets.get("ARGOS_V2_BSKY_HANDLE") or secrets.get("BSKY_HANDLE")
    pw = secrets.get("ARGOS_V2_BSKY_APP_PASSWORD") or secrets.get("BSKY_APP_PASSWORD")
    if not (handle and pw):
        _logmsg("missing BSKY creds")
        return

    try:
        from atproto import Client
        from self_label import ensure_bot_self_label
    except Exception as e:
        _logmsg(f"import error: {e}")
        return

    client = Client()
    try:
        client.login(handle, pw)
        ensure_bot_self_label(client)
    except Exception as e:
        _logmsg(f"login failed: {e}")
        return

    # Rotate target handles per fire so we sample different parts of the graph
    rng = random.Random(int(time.time() // 1800))
    rotated = TARGET_HANDLES[:]
    rng.shuffle(rotated)

    candidates = []
    for h in rotated[:5]:  # only ~5 handles per fire to limit API calls
        candidates.extend(fetch_recent_posts(client, h, hours=24, max_n=10))
        time.sleep(0.4)

    if not candidates:
        _logmsg("no candidate posts found")
        return

    # Filter: exclude posts we've already replied to today
    seen = set(counter.get("recent_uris", []))
    candidates = [c for c in candidates if c["uri"] not in seen]

    # Prefer mid-engagement (visible without being saturated): 5-200 likes
    candidates.sort(key=lambda c: abs(c["like_count"] - 30))
    candidates = candidates[:10]
    _logmsg(f"{len(candidates)} candidate posts after filters")

    decision = draft_reply(candidates, secrets)
    if not decision or not decision.get("chosen_uri") or not decision.get("reply"):
        _logmsg(f"no draft produced: {decision}")
        return

    chosen = next((c for c in candidates if c["uri"] == decision["chosen_uri"]), None)
    if not chosen:
        _logmsg(f"chosen uri {decision['chosen_uri']} not in candidates")
        return

    reply_text = decision["reply"].strip()
    if len(reply_text) < 40 or len(reply_text) > 290:
        _logmsg(f"reply length out of bounds ({len(reply_text)} chars)")
        return

    # Slop check at threshold 50 (replies are more scrutinized)
    try:
        from slop_checker import is_publish_safe
        safe, verdict = is_publish_safe(reply_text, threshold=50)
        if not safe:
            _logmsg(f"slop check BLOCKED at {verdict.get('ai_prob')}%: {verdict.get('flags', [])[:2]}")
            _append_history({
                "at": _now_utc().isoformat(),
                "target_uri": chosen["uri"],
                "target_author": chosen["author_handle"],
                "reply_attempted": reply_text,
                "blocked_by": "slop_checker",
                "ai_prob": verdict.get("ai_prob"),
            })
            return
    except Exception as e:
        _logmsg(f"slop check error (continuing): {e}")

    _logmsg(f"replying to @{chosen['author_handle']} / {chosen['uri'].split('/')[-1]}")
    _logmsg(f"  reply: {reply_text}")

    result = post_reply(client, chosen["uri"], chosen["cid"], reply_text)
    if result.get("ok"):
        counter["count"] += 1
        counter["last_posted_at"] = time.time()
        counter.setdefault("recent_uris", []).append(chosen["uri"])
        _save_counter(counter)
        _append_history({
            "at": _now_utc().isoformat(),
            "target_uri": chosen["uri"],
            "target_author": chosen["author_handle"],
            "reply": reply_text,
            "reply_uri": result["uri"],
            "rationale": decision.get("rationale"),
        })
        _logmsg(f"  ✓ posted ({counter['count']}/{MAX_PER_DAY})")
        _notify_operator(
            f"bluesky reply: @{chosen['author_handle']}\n\n"
            f"their post: {chosen['text'][:140]}...\n\n"
            f"my reply: \"{reply_text}\"\n\n"
            f"({counter['count']}/{MAX_PER_DAY} today · {decision.get('rationale', '')})"
        )
    else:
        _logmsg(f"  ✗ failed: {result.get('error')}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
