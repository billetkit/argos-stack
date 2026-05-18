"""channel_health.py — Daily shadowban / silence detector across all distribution channels.

For each platform we publish on, check from an UNAUTHENTICATED context that
recent posts are actually visible. Silent shadowbans are the failure mode that
hurts most because the bot keeps "succeeding" while accumulating zero signal.

For each channel:
  1. Hit the public-facing endpoint (no auth) that should return recent activity
  2. Compare to what we LOG ourselves shipped recently (counter files + history)
  3. If we shipped N posts but public-facing returns < N (or 0), flag silent
  4. Operator notification via outbox if anything is silently dropped

Runs nightly via LaunchAgent. Output: memory/channel-health-history.json + an
alert when anomalies appear.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import time
from typing import Any

import requests

ROOT = pathlib.Path("/Users/argos/argos")
MEMORY = ROOT / "memory"
LOG = MEMORY / "channel-health.log"
HISTORY = MEMORY / "channel-health-history.json"
OUTBOX = MEMORY / "operator-outbox"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.open("a").write(f"[{_now()}] {msg}\n")
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


# ---- per-channel probes ----

def probe_bluesky(secrets: dict) -> dict:
    handle = secrets.get("ARGOS_V2_BSKY_HANDLE") or secrets.get("BSKY_HANDLE") or "argosops.bsky.social"
    try:
        r = requests.get(
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            params={"actor": handle, "limit": 20},
            timeout=10,
        )
        if r.status_code != 200:
            return {"channel": "bluesky", "ok": False, "error": f"http {r.status_code}"}
        feed = r.json().get("feed", [])
        # last 24h
        cutoff = time.time() - 86400
        recent = []
        for f in feed:
            p = f.get("post", {})
            try:
                ts = datetime.datetime.fromisoformat(p.get("indexedAt", "").replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if ts >= cutoff:
                recent.append({"uri": p.get("uri"), "indexedAt": p.get("indexedAt")})
        # Compare to what bluesky publisher claims shipped today
        counter_file = MEMORY / "bluesky-publish-counter.json"
        shipped_today = 0
        if counter_file.exists():
            try:
                shipped_today = json.loads(counter_file.read_text()).get("count", 0)
            except Exception:
                pass
        replies_counter = MEMORY / "bluesky-replies-counter.json"
        replies_today = 0
        if replies_counter.exists():
            try:
                replies_today = json.loads(replies_counter.read_text()).get("count", 0)
            except Exception:
                pass
        return {
            "channel": "bluesky",
            "handle": handle,
            "public_recent_24h": len(recent),
            "shipped_today": shipped_today + replies_today,
            "ok": True,
            "silent": (shipped_today + replies_today) > 0 and len(recent) == 0,
        }
    except Exception as e:
        return {"channel": "bluesky", "ok": False, "error": f"{type(e).__name__}: {e}"}


def probe_reddit(secrets: dict) -> dict:
    # Try to read username from saved identity file
    id_file = MEMORY / "reddit-identity.json"
    username = None
    if id_file.exists():
        try:
            username = json.loads(id_file.read_text()).get("username")
        except Exception:
            pass
    if not username:
        return {"channel": "reddit", "ok": False, "error": "no username known"}

    try:
        # /user/<name>/about.json works without auth
        r = requests.get(
            f"https://www.reddit.com/user/{username}/about.json",
            headers={"User-Agent": "billetkit-channel-health/0.1"},
            timeout=10,
        )
        if r.status_code != 200:
            return {"channel": "reddit", "username": username, "ok": False, "error": f"http {r.status_code} (possible suspension or username change)"}
        data = r.json().get("data", {})
        # Also: list recent comments to confirm they're visible
        rc = requests.get(
            f"https://www.reddit.com/user/{username}/comments.json",
            params={"limit": 10},
            headers={"User-Agent": "billetkit-channel-health/0.1"},
            timeout=10,
        )
        comments_visible = []
        if rc.status_code == 200:
            for c in rc.json().get("data", {}).get("children", []):
                comments_visible.append({"id": c.get("data", {}).get("id"), "subreddit": c.get("data", {}).get("subreddit"), "created_utc": c.get("data", {}).get("created_utc")})
        # Compare to our warmer's claim
        warmer_history = MEMORY / "reddit-warmer-history.json"
        my_posts_today = 0
        if warmer_history.exists():
            try:
                h = json.loads(warmer_history.read_text())
                cutoff = time.time() - 86400
                my_posts_today = sum(1 for e in h if e.get("result") == "posted" and datetime.datetime.fromisoformat(e["at"]).timestamp() >= cutoff)
            except Exception:
                pass
        return {
            "channel": "reddit",
            "username": username,
            "comment_karma": data.get("comment_karma", 0),
            "link_karma": data.get("link_karma", 0),
            "is_suspended": data.get("is_suspended", False),
            "public_recent_comments": len(comments_visible),
            "my_warmer_posts_today": my_posts_today,
            "silent": my_posts_today > 0 and len(comments_visible) == 0,
            "ok": True,
        }
    except Exception as e:
        return {"channel": "reddit", "username": username, "ok": False, "error": f"{type(e).__name__}: {e}"}


def probe_hn(secrets: dict) -> dict:
    # HN doesn't expose a "list user's recent comments" endpoint via API,
    # but /v0/user/{name}.json gives karma + recent submitted IDs
    # The username is the HN username — we may not have it stored yet.
    # For now: skip if no HN_USERNAME secret. Operator can add it after first warmer post.
    username = secrets.get("BILLETKIT_HN_USERNAME") or secrets.get("HN_USERNAME")
    if not username:
        # try to extract from saved cookie context? skip for now.
        return {"channel": "hn", "ok": False, "error": "no HN_USERNAME in secrets (add after first comment)"}
    try:
        r = requests.get(f"https://hacker-news.firebaseio.com/v0/user/{username}.json", timeout=10)
        if r.status_code != 200:
            return {"channel": "hn", "username": username, "ok": False, "error": f"http {r.status_code}"}
        data = r.json() or {}
        karma = data.get("karma", 0)
        submitted = data.get("submitted", [])
        # Check the 5 most recent are visible (not dead)
        recent_visible = 0
        for sid in submitted[:5]:
            try:
                ri = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5).json() or {}
                if not ri.get("dead") and not ri.get("deleted"):
                    recent_visible += 1
            except Exception:
                pass
            time.sleep(0.1)
        return {
            "channel": "hn",
            "username": username,
            "karma": karma,
            "recent_visible_of_5": recent_visible,
            "silent": len(submitted) > 0 and recent_visible == 0,
            "ok": True,
        }
    except Exception as e:
        return {"channel": "hn", "username": username, "ok": False, "error": f"{type(e).__name__}: {e}"}


def probe_mastodon(secrets: dict) -> dict:
    instance = secrets.get("MASTODON_INSTANCE_URL", "").rstrip("/")
    if not instance:
        return {"channel": "mastodon", "ok": False, "error": "MASTODON_INSTANCE_URL not set"}
    # We need the username to probe — derive from access token whoami if possible
    token = secrets.get("MASTODON_ACCESS_TOKEN")
    if not token:
        return {"channel": "mastodon", "ok": False, "error": "MASTODON_ACCESS_TOKEN not set"}
    try:
        r = requests.get(
            f"{instance}/api/v1/accounts/verify_credentials",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return {"channel": "mastodon", "ok": False, "error": f"http {r.status_code}"}
        me = r.json()
        username = me.get("acct") or me.get("username")
        # public statuses for this user
        rs = requests.get(
            f"{instance}/api/v1/accounts/{me['id']}/statuses",
            params={"limit": 10},
            timeout=10,
        )
        recent = rs.json() if rs.status_code == 200 else []
        return {
            "channel": "mastodon",
            "instance": instance,
            "username": username,
            "followers": me.get("followers_count", 0),
            "statuses_count": me.get("statuses_count", 0),
            "public_recent_visible": len(recent),
            "ok": True,
        }
    except Exception as e:
        return {"channel": "mastodon", "ok": False, "error": f"{type(e).__name__}: {e}"}


def notify_operator(text: str) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
    (OUTBOX / f"{ts}-channel-health.md").write_text(text)


def main():
    secrets = _load_secrets()
    _log("--- channel-health probe ---")

    results = []
    for fn in (probe_bluesky, probe_reddit, probe_hn, probe_mastodon):
        r = fn(secrets)
        results.append(r)
        _log(f"  {r.get('channel')}: {json.dumps({k: v for k, v in r.items() if k != 'channel'})[:200]}")

    # Append to history
    snap = {"at": _now(), "results": results}
    hist = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    hist.append(snap)
    # cap history at 90 snapshots
    if len(hist) > 90:
        hist = hist[-90:]
    HISTORY.write_text(json.dumps(hist, indent=2))

    # Alert on silent shadowbans
    silent = [r for r in results if r.get("silent")]
    if silent:
        body = "channel-health: possible shadowban detected\n\n"
        for r in silent:
            body += f"- {r['channel']}: claimed activity exists but public view shows {r.get('public_recent_24h', r.get('public_recent_comments', 'unknown'))} items\n"
        body += "\ninvestigate by checking the affected channel logged-out from your phone."
        notify_operator(body)
        _log(f"⚠ silent shadowban suspected on: {[r['channel'] for r in silent]}")


if __name__ == "__main__":
    main()
