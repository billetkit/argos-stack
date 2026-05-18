"""hn_warmer.py — Hacker News karma warmup via thoughtful comments.

Same pattern as reddit_warmer. HN has no real karma minimum for commenting,
but a Show HN submission from a 0-karma account gets buried instantly. Build
karma here so the eventual Show HN of billetkit/argos-stack has standing.

Per-fire flow:
  1. Gates: cap, gap, quiet hours, rng
  2. Pull recent stories from HN's public API (topstories.json + item/{id}.json)
  3. Filter to stories where billetkit has technical context
  4. Haiku picks one + drafts a comment
  5. Slop check at threshold 50
  6. Post via Playwright (persistent profile, HN login was wizard-seeded)
  7. Log + operator notification

Cap: 3/day. Min gap: 3h between comments. Quiet 2-7am.
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

log = logging.getLogger("hn-warmer")

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent
MEMORY = ROOT / "memory"
LOG = MEMORY / "hn-warmer.log"
COUNTER = MEMORY / "hn-warmer-counter.json"
HISTORY = MEMORY / "hn-warmer-history.json"
OUTBOX = MEMORY / "operator-outbox"
PROFILE_DIR = pathlib.Path("/Users/argos/.argos-browser-profile")

sys.path.insert(0, str(_THIS.parent))

# billetkit context keywords — bias the story filter toward what we can credibly add to
RELEVANCE_KEYWORDS = [
    "mcp", "model context protocol", "agent", "autonomous", "claude", "anthropic",
    "ollama", "qwen", "llama", "mlx", "playwright", "automation", "scraping",
    "indie hacker", "solo founder", "saas", "stripe", "side project",
    "self-hosted", "local llm", "mac mini", "apple silicon", "m1", "m2", "m3", "m4",
    "fine-tune", "lora", "rag", "embedding", "vector", "langfuse", "litellm",
    "ai detection", "pangram", "gptzero", "voice", "bot", "telegram", "bluesky",
]

MAX_PER_DAY = 3
MIN_HOURS_BETWEEN = 3.0
LOCAL_TZ_QUIET_START_HOUR = 2
LOCAL_TZ_QUIET_END_HOUR = 7
DRAW_PROBABILITY = 0.35


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
        return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_ids": []}
    try:
        d = json.loads(COUNTER.read_text())
        if d.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_ids": d.get("recent_ids", [])[-60:]}
        return d
    except Exception:
        return {"date": _today_utc(), "count": 0, "last_posted_at": None, "recent_ids": []}


def _save_counter(d: dict) -> None:
    if "recent_ids" in d and len(d["recent_ids"]) > 60:
        d["recent_ids"] = d["recent_ids"][-60:]
    COUNTER.write_text(json.dumps(d))


def _append_history(entry: dict) -> None:
    h = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    h.append(entry)
    HISTORY.write_text(json.dumps(h, indent=2))


def _notify_operator(text: str) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = _now_utc().strftime("%Y-%m-%dT%H%M%S")
    (OUTBOX / f"{ts}-hn-warmer.md").write_text(text)


def _gates_ok(counter: dict) -> tuple[bool, str]:
    if counter["count"] >= MAX_PER_DAY:
        return False, f"cap_reached"
    if counter.get("last_posted_at"):
        delta_h = (time.time() - counter["last_posted_at"]) / 3600
        if delta_h < MIN_HOURS_BETWEEN:
            return False, f"too_soon ({delta_h:.1f}h)"
    h = _local_hour()
    if LOCAL_TZ_QUIET_START_HOUR <= h < LOCAL_TZ_QUIET_END_HOUR:
        return False, f"quiet_hours ({h:02d}h)"
    if random.random() > DRAW_PROBABILITY:
        return False, "rng_skip"
    return True, "ok"


# HN API: hacker-news.firebaseio.com
HN_API = "https://hacker-news.firebaseio.com/v0"


def fetch_relevant_stories(limit: int = 40) -> list:
    """Pull top stories + filter for billetkit-relevance."""
    try:
        ids = requests.get(f"{HN_API}/topstories.json", timeout=10).json()[:limit]
    except Exception as e:
        _logmsg(f"topstories fetch failed: {e}")
        return []
    stories = []
    for sid in ids:
        try:
            s = requests.get(f"{HN_API}/item/{sid}.json", timeout=8).json()
            if not s or s.get("dead") or s.get("deleted"):
                continue
            if s.get("type") != "story":
                continue
            # filter: must have some discussion
            kids = s.get("kids", []) or []
            if len(kids) < 2 or len(kids) > 200:
                continue
            title = (s.get("title") or "").lower()
            text = (s.get("text") or "").lower()
            blob = title + " " + text + " " + (s.get("url") or "").lower()
            # Score relevance
            matches = sum(1 for kw in RELEVANCE_KEYWORDS if kw in blob)
            if matches < 1:
                continue
            age_h = (time.time() - s.get("time", 0)) / 3600
            if age_h < 1 or age_h > 24:  # comment window: 1h-24h
                continue
            stories.append({
                "id": s["id"],
                "title": s.get("title", ""),
                "url": s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}",
                "text": s.get("text") or "",
                "by": s.get("by"),
                "score": s.get("score", 0),
                "descendants": s.get("descendants", 0),
                "age_h": round(age_h, 1),
                "relevance": matches,
                "comment_url": f"https://news.ycombinator.com/item?id={s['id']}",
            })
            time.sleep(0.05)
        except Exception:
            continue
    # Sort by relevance, then by mid-engagement (sweet spot 20-200 comments)
    stories.sort(key=lambda s: (-s["relevance"], abs(s["descendants"] - 80)))
    return stories[:12]


def fetch_top_comments(story_id: int, limit: int = 5) -> list:
    """Pull a few top-level comments for context."""
    try:
        s = requests.get(f"{HN_API}/item/{story_id}.json", timeout=8).json()
    except Exception:
        return []
    kids = (s.get("kids") or [])[:limit]
    out = []
    for cid in kids:
        try:
            c = requests.get(f"{HN_API}/item/{cid}.json", timeout=8).json()
            if not c or c.get("deleted") or c.get("dead"):
                continue
            out.append({"by": c.get("by"), "text": (c.get("text") or "")[:600]})
        except Exception:
            continue
    return out


DRAFT_PROMPT = """You are billetkit on Hacker News, account roughly 0 karma. Goal: write ONE thoughtful comment on a story that adds a specific technical observation. Build karma honestly.

Voice rules (HN is brutal about low-effort + AI-slop comments):
- 80-280 characters. Concise is rewarded.
- Specific. ONE concrete number, named tool, or contrarian observation.
- HN voice register: technical, dry, slightly skeptical, ZERO hype words.
- NO em-dashes. NO exclamation. NO "great post".
- ANTI-TELL BANNED: delve, tapestry, leverage, harness, utilize, robust, seamless, cutting-edge, multifaceted, synergy, foster, holistic, streamline, elevate, empower, comprehensive, furthermore, moreover.
- DO NOT mention billetkit / argos-stack / github repo. Just be a thoughtful HN commenter.
- Fragment sentences OK.
- "I tried X and got Y" beats "X is interesting because Z"

Decision: pick ONE story you have genuine technical context to add to. Prefer mid-engagement (20-150 comments) and stories where the discussion is still wide-open.

Return ONLY JSON:
{
  "chosen_id": <hn story id>,
  "comment": "<the comment text, 80-280 chars>",
  "rationale": "<one sentence>"
}

If no fit: {"chosen_id": null, "comment": null, "rationale": "no fit"}"""


def draft_comment(stories: list, secrets: dict) -> Optional[dict]:
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY", "")
    use_proxy = bool(master_key) and secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "haiku" if use_proxy else "claude-haiku-4-5"

    blob = json.dumps([
        {
            "id": s["id"], "title": s["title"], "url": s["url"], "text": s["text"][:500],
            "comments": s["descendants"], "score": s["score"], "age_h": s["age_h"],
            "top_comments": s.get("top_comments", [])[:4],
        }
        for s in stories
    ], indent=2)

    r = requests.post(endpoint, json={
        "model": model, "max_tokens": 500,
        "system": DRAFT_PROMPT,
        "messages": [{"role": "user", "content": f"Stories:\n\n{blob}"}],
    }, headers={"x-api-key": auth_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, timeout=30)
    if not r.ok:
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


def post_comment(story_id: int, comment_text: str) -> dict:
    """Post a comment via Playwright with the persistent profile."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"ok": False, "error": f"playwright: {e}"}

    if not PROFILE_DIR.exists():
        return {"ok": False, "error": "profile dir missing"}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            args=["--no-first-run", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            url = f"https://news.ycombinator.com/item?id={story_id}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # HN: confirm we're logged in
            logged_in = page.locator("a#logout").count() > 0
            if not logged_in:
                # Check for "login" link in nav — that's the unauthenticated state
                ctx.close()
                return {"ok": False, "error": "not logged in (run login-wizard for hn)"}

            # The comment textarea is `<textarea name="text">` on item pages
            box = page.locator("textarea[name='text']").first
            if not box.is_visible():
                ctx.close()
                return {"ok": False, "error": "comment textarea not visible — maybe rate-limited"}
            box.click()
            time.sleep(0.5)
            page.keyboard.type(comment_text, delay=random.randint(20, 60))
            time.sleep(1)

            # Submit — HN has a value="add comment" button
            submit = page.locator("input[type='submit'][value*='comment'], input[type='submit'][value*='add']").first
            if not submit.is_visible():
                submit = page.locator("input[type='submit']").first
            submit.click()
            time.sleep(3)

            new_url = page.url
            ctx.close()
            # HN redirects to /item?id=<story> after posting; we don't get a direct comment URL easily
            return {"ok": True, "url": new_url}
        except Exception as e:
            try:
                ctx.close()
            except Exception:
                pass
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main():
    secrets = _load_secrets()
    if secrets.get("BILLETKIT_HN_WARMER_DISABLED", "").lower() == "true":
        return

    counter = _load_counter()
    ok, reason = _gates_ok(counter)
    if not ok:
        if reason.startswith("cap_reached") or reason.startswith("too_soon"):
            _logmsg(f"skip · {reason}")
        return

    _logmsg(f"--- hn-warmer tick (cap={counter['count']}/{MAX_PER_DAY}) ---")

    stories = fetch_relevant_stories(limit=40)
    if not stories:
        _logmsg("no relevant stories")
        return

    # filter out stories we've already commented on today
    seen = set(counter.get("recent_ids", []))
    stories = [s for s in stories if s["id"] not in seen]
    if not stories:
        _logmsg("all relevant stories already commented")
        return

    # enrich top 6 with comments
    for s in stories[:6]:
        s["top_comments"] = fetch_top_comments(s["id"], limit=4)
        time.sleep(0.2)

    decision = draft_comment(stories[:6], secrets)
    if not decision or not decision.get("chosen_id") or not decision.get("comment"):
        _logmsg(f"no draft: {decision}")
        return

    chosen = next((s for s in stories if s["id"] == decision["chosen_id"]), None)
    if not chosen:
        _logmsg(f"chosen id {decision['chosen_id']} not in candidates")
        return

    comment = decision["comment"].strip()
    if len(comment) < 60 or len(comment) > 320:
        _logmsg(f"comment len out of bounds ({len(comment)})")
        return

    # Slop check
    try:
        from slop_checker import is_publish_safe
        safe, verdict = is_publish_safe(comment, threshold=50)
        if not safe:
            _logmsg(f"SLOP BLOCK at {verdict.get('ai_prob')}%: {verdict.get('flags', [])[:2]}")
            _append_history({
                "at": _now_utc().isoformat(),
                "story_id": chosen["id"],
                "comment_attempted": comment,
                "blocked": "slop", "ai_prob": verdict.get("ai_prob"),
            })
            return
    except Exception as e:
        _logmsg(f"slop check error: {e}")

    _logmsg(f"posting to HN story {chosen['id']} · \"{chosen['title'][:60]}\"")
    _logmsg(f"  comment: {comment}")

    result = post_comment(chosen["id"], comment)
    if result.get("ok"):
        counter["count"] += 1
        counter["last_posted_at"] = time.time()
        counter.setdefault("recent_ids", []).append(chosen["id"])
        _save_counter(counter)
        _append_history({
            "at": _now_utc().isoformat(),
            "story_id": chosen["id"],
            "story_title": chosen["title"],
            "story_url": chosen["url"],
            "comment_url": chosen["comment_url"],
            "comment": comment,
            "rationale": decision.get("rationale"),
        })
        _logmsg(f"  ✓ posted ({counter['count']}/{MAX_PER_DAY})")
        _notify_operator(
            f"hn warmup: commented on \"{chosen['title'][:100]}\"\n\n"
            f"{chosen['comment_url']}\n\n"
            f"my comment: \"{comment}\"\n\n"
            f"({counter['count']}/{MAX_PER_DAY} today · {decision.get('rationale', '')})"
        )
    else:
        _logmsg(f"  ✗ failed: {result.get('error')}")
        _append_history({
            "at": _now_utc().isoformat(),
            "story_id": chosen["id"],
            "comment_attempted": comment,
            "result": "failed",
            "error": result.get("error"),
        })


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
