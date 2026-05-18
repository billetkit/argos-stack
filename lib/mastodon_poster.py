"""mastodon_poster.py — Federated cross-rail. API-based, much more permissive than Bluesky/X.

Mastodon doesn't algorithm-suppress AI accounts and has explicit support for bot
labeling. Posts go via the standard /api/v1/statuses endpoint with bearer token.

Required secrets:
  MASTODON_INSTANCE_URL    e.g. https://mastodon.social, https://fosstodon.org
  MASTODON_ACCESS_TOKEN    from Mastodon → Settings → Development → New Application
                            (scopes: read, write:statuses)
  MASTODON_BOT_LABEL       optional, defaults to "true" (sets is_bot on each post)

Operator setup (one-time, ~3 min):
  1. Pick an AI-friendly Mastodon instance. Recommendations:
     - mastodon.social (largest, general)
     - hachyderm.io (tech-focused, requires brief sign-up review)
     - fosstodon.org (FOSS focus, billetkit-aligned audience)
     - tech.lgbt or sigmoid.social (AI/ML communities)
  2. Sign up. Set the account "Profile metadata" with bot=true.
  3. Settings → Development → New application
     - Name: "billetkit autoposter"
     - Scopes: read, write:statuses (you can untick everything else)
     - Submit, then copy the "Your access token" value
  4. Add to ~/.openclaw/secrets.env:
     export MASTODON_INSTANCE_URL="https://your-instance"
     export MASTODON_ACCESS_TOKEN="<the token>"
  5. Drop drafts into ~/argos/memory/mastodon-queue/*.md
  6. This runs on the heartbeat tick same as Bluesky publisher (or via its own LaunchAgent)
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import sys
from typing import Optional

import requests

log = logging.getLogger(__name__)

_THIS = pathlib.Path(__file__).resolve()
ROOT = _THIS.parent.parent
MEMORY = ROOT / "memory"
QUEUE = MEMORY / "mastodon-queue"
PUBLISHED = MEMORY / "mastodon-published"
SLOP = MEMORY / "mastodon-slop"
COUNTER = MEMORY / "mastodon-publish-counter.json"
LOG_FILE = MEMORY / "mastodon-poster.log"

sys.path.insert(0, str(_THIS.parent))


def _ts() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")


def _today_utc() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.open("a").write(f"[{datetime.datetime.now(datetime.UTC).isoformat()}] {msg}\n")
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
        return {"date": _today_utc(), "count": 0}
    try:
        d = json.loads(COUNTER.read_text())
        if d.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0}
        return d
    except Exception:
        return {"date": _today_utc(), "count": 0}


def _save_counter(d: dict) -> None:
    COUNTER.write_text(json.dumps(d))


def _clean_body(raw: str) -> str:
    text = raw
    text = re.split(r"\n---\n_Auto-graded:", text, maxsplit=1)[0]
    text = re.sub(
        r"^#\s*Proactive draft[^\n]*\n+(?:_[^\n]*_\n+)?---\n+",
        "", text, flags=re.MULTILINE,
    )
    lines = text.splitlines()
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)
    text = "\n".join(lines).strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def publish_next(dry_run: bool = False) -> dict:
    secrets = _load_secrets()
    instance = secrets.get("MASTODON_INSTANCE_URL", "").rstrip("/")
    token = secrets.get("MASTODON_ACCESS_TOKEN")
    bot_label = secrets.get("MASTODON_BOT_LABEL", "true").lower() == "true"
    cap = int(secrets.get("BILLETKIT_MASTODON_DAY_CAP", "6"))

    if not instance or not token:
        return {"action": "not_configured", "hint": "set MASTODON_INSTANCE_URL + MASTODON_ACCESS_TOKEN in secrets.env"}

    counter = _load_counter()
    if counter["count"] >= cap:
        return {"action": "rate_capped", "today": counter["count"], "cap": cap}

    if not QUEUE.exists():
        return {"action": "queue_empty"}
    drafts = sorted(p for p in QUEUE.glob("*.md") if p.is_file())
    if not drafts:
        return {"action": "queue_empty"}

    path = drafts[0]
    body = _clean_body(path.read_text())
    # Mastodon default char limit is 500 (some instances allow more); use 480 to be safe
    max_chars = int(secrets.get("MASTODON_MAX_CHARS", "480"))
    if len(body) < 10 or len(body) > max_chars:
        return {"action": "bad_length", "chars": len(body), "max": max_chars}

    # Slop check
    if secrets.get("BILLETKIT_SKIP_SLOP_CHECK", "").lower() != "true":
        try:
            from slop_checker import is_publish_safe
            threshold = int(secrets.get("BILLETKIT_MASTODON_SLOP_THRESHOLD", "60"))
            safe, verdict = is_publish_safe(body, threshold=threshold)
            if not safe:
                SLOP.mkdir(parents=True, exist_ok=True)
                target = SLOP / path.name
                target.write_text(
                    f"{path.read_text().rstrip()}\n\n---\n"
                    f"_Slop check: {verdict.get('ai_prob')}% AI-prob (threshold {threshold})_\n"
                    f"_Flags: {' · '.join(verdict.get('flags', []))}_\n"
                    f"_Hint: {verdict.get('rewrite_hint', '')}_\n"
                )
                path.unlink()
                return {"action": "slop_blocked", "ai_prob": verdict.get("ai_prob"), "path": str(target)}
        except Exception as e:
            _log(f"slop check error: {e}")

    if dry_run:
        return {"action": "would_publish", "body": body, "chars": len(body), "today": counter["count"], "cap": cap}

    # POST /api/v1/statuses
    try:
        r = requests.post(
            f"{instance}/api/v1/statuses",
            data={
                "status": body,
                "visibility": "public",
                "language": "en",
                # Mastodon doesn't have a per-post is_bot flag — that's set on the account profile.
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        post_url = data.get("url") or data.get("uri")
    except Exception as e:
        return {"action": "error", "error": f"{type(e).__name__}: {e}"}

    # Success
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    target = PUBLISHED / path.name
    target.write_text(
        f"# Published · {datetime.datetime.now(datetime.UTC).isoformat()}\n\n"
        f"- url: {post_url}\n- instance: {instance}\n- chars: {len(body)}\n\n---\n\n{body}\n"
    )
    path.unlink()
    counter["count"] += 1
    _save_counter(counter)
    return {"action": "published", "url": post_url, "today": counter["count"], "cap": cap}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = publish_next(dry_run=args.dry_run)
    print(json.dumps(r, indent=2))
