#!/usr/bin/env python3
"""anthropic-rss.py — Watch Anthropic's news/blog RSS for new posts.

Polls the Anthropic news RSS feed (every 6 hours via LaunchAgent), compares
against last-seen list, surfaces new entries to operator's Telegram with a
Haiku-generated TL;DR.

This is the "Anthropic just dropped a new feature / Claude version / pricing change"
early-warning system.
"""
import os, json, pathlib, datetime, re
import requests
from xml.etree import ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
INTEL = MEMORY / "intel"
INTEL.mkdir(parents=True, exist_ok=True)
SEEN_FILE = INTEL / "anthropic-rss-seen.json"

ANTHROPIC_RSS = "https://www.anthropic.com/news/rss.xml"
# Fallback in case the news RSS path changes
FALLBACK_RSS = "https://www.anthropic.com/news"


def load_secrets():
    p = pathlib.Path.home() / ".openclaw" / "secrets.env"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"').strip("'")
    return out


def fetch_rss():
    """Return list of {title, link, pubDate, description}."""
    try:
        r = requests.get(ANTHROPIC_RSS, timeout=15, headers={"User-Agent": "billetkit/1.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = []
        # RSS 2.0 path: rss > channel > item
        for item in root.findall(".//item"):
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "pubDate": (item.findtext("pubDate") or "").strip(),
                "description": (item.findtext("description") or "").strip()[:600],
            })
        return items
    except Exception as e:
        print(f"fetch error: {e}", flush=True)
        return []


def summarize(new_items, secrets):
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "haiku" if use_proxy else "claude-haiku-4-5"

    item_blocks = []
    for it in new_items[:5]:
        item_blocks.append(f"TITLE: {it['title']}\nDATE: {it['pubDate']}\nLINK: {it['link']}\nEXCERPT: {it['description'][:400]}")

    system = """You are billetkit. Anthropic just published new content. Summarize for your operator who runs an autonomous agent business on Claude API.

For each new post: 1-line summary + 1-line "what this means for billetkit operations". Be specific about API changes, pricing changes, new models, new features.

FORMAT:

[1] <title>
    <link>
    — what: <one sentence>
    — billetkit impact: <one sentence>

If a post is general PR / company-update that doesn't affect operators, still include it but say so explicitly in the impact line.

VOICE: lowercase first words. No emojis. No exclamation points. Dry.
LENGTH: 100-250 words total."""

    user = "New Anthropic posts:\n\n" + "\n\n---\n\n".join(item_blocks) + "\n\nCompose the brief now."

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 700,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, headers={
            "x-api-key": auth_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"summarize error: {e}", flush=True)
        return None


def main():
    print(f"[anthropic-rss] starting at {datetime.datetime.now()}", flush=True)
    items = fetch_rss()
    print(f"[anthropic-rss] fetched {len(items)} items", flush=True)
    if not items:
        return

    seen = set()
    if SEEN_FILE.exists():
        try:
            seen = set(json.load(SEEN_FILE.open()).get("seen", []))
        except Exception:
            pass

    new_items = [it for it in items if it["link"] not in seen]
    print(f"[anthropic-rss] {len(new_items)} new since last poll", flush=True)

    # Update seen
    SEEN_FILE.write_text(json.dumps({
        "seen": list(seen | {it["link"] for it in items}),
        "last_polled": datetime.datetime.now().isoformat(),
    }))

    if not new_items:
        print("[anthropic-rss] no new Anthropic posts", flush=True)
        return

    secrets = load_secrets()
    brief = summarize(new_items, secrets) or (
        "Fallback: " + "; ".join(f"{it['title']} ({it['link']})" for it in new_items[:3])
    )

    # Persist + queue to Telegram
    today = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    p = INTEL / f"anthropic-{today}.md"
    p.write_text(f"# Anthropic · {today}\n\n{brief}\n")

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
    out = MEMORY / "operator-outbox" / f"{ts}-anthropic-news.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"🟠 Anthropic news\n\n{brief}")
    print(f"[anthropic-rss] queued for Telegram: {out.name}", flush=True)


if __name__ == "__main__":
    main()
