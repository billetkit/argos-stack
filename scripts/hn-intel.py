#!/usr/bin/env python3
"""hn-intel.py — Nightly Hacker News intelligence scraper for billetkit.

Pulls top 30 HN stories, filters for relevance to autonomous agent operators,
summarizes via Sonnet, saves to v2/memory/intel/ and optionally surfaces high-signal
items to the operator's morning digest.

Free, no auth, single endpoint (HN's Firebase API).

Fires nightly via LaunchAgent (StartCalendarInterval at 06:30 local).
"""
import os, sys, json, time, pathlib, datetime, re
import requests
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
INTEL = MEMORY / "intel"
INTEL.mkdir(parents=True, exist_ok=True)

HN_API = "https://hacker-news.firebaseio.com/v0"

# Keyword filter — items containing any of these in title or url get included
RELEVANT_PATTERNS = [
    r"\bai\b", r"\bagent\b", r"\bllm\b", r"\bclaude\b", r"\banthropic\b", r"\bopenai\b",
    r"\bgpt\b", r"\bsonnet\b", r"\bopus\b", r"\bopenclaw\b", r"\bclawbot\b",
    r"\bautonomous\b", r"\bmcp\b", r"\bvector\b", r"\brag\b", r"\bfine[- ]?tun",
    r"\blangchain\b", r"\blanggraph\b", r"\bcrewai\b", r"\bdspy\b",
    r"\bollama\b", r"\bvllm\b", r"\bllama\b", r"\bqwen\b", r"\bmistral\b", r"\bdeepseek\b",
    r"\bflux\b", r"\bsdxl\b", r"\bdiffuser", r"\bcomfyui\b",
    r"\bstripe\b", r"\bclawmart\b", r"\bgumroad\b", r"\bpolar\b",
    r"\bbluesky\b", r"\batproto\b", r"\bclawhub\b",
    r"\bindie hacker\b", r"\bsolo founder\b", r"\bsaas\b",
    r"\bfelix craft\b", r"\bheyron\b", r"\bpieter levels\b",
]
RELEVANCE_REGEX = re.compile("|".join(RELEVANT_PATTERNS), re.IGNORECASE)


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


def fetch_item(item_id):
    try:
        r = requests.get(f"{HN_API}/item/{item_id}.json", timeout=10)
        return r.json()
    except Exception:
        return None


def fetch_top_stories(n=50):
    """Return list of (rank, story_dict). Pulls top N story IDs then fetches each in parallel."""
    r = requests.get(f"{HN_API}/topstories.json", timeout=10)
    ids = r.json()[:n]
    with ThreadPoolExecutor(max_workers=10) as ex:
        items = list(ex.map(fetch_item, ids))
    return [(i + 1, item) for i, item in enumerate(items) if item]


def is_relevant(story):
    title = (story.get("title") or "").strip()
    url = (story.get("url") or "").strip()
    return bool(RELEVANCE_REGEX.search(title + " " + url))


def summarize_via_sonnet(items, secrets):
    """Have Sonnet pick the 3-5 most important + write a tight summary."""
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "sonnet" if use_proxy else "claude-sonnet-4-5"

    item_lines = []
    for rank, item in items[:25]:
        title = item.get("title", "?")
        url = item.get("url", f"https://news.ycombinator.com/item?id={item.get('id')}")
        score = item.get("score", 0)
        comments = item.get("descendants", 0)
        item_lines.append(f"#{rank} ({score}↑ {comments}💬) {title}  →  {url}")

    system = """You are Argos / billetkit, surveying overnight Hacker News activity for your operator. They run an autonomous AI agent business and care about things relevant to that lane: agent frameworks, LLM tooling, MCP servers, indie-hacker monetization, ClawMart skills, AI hosting, image gen, anything that informs the work.

Pick the 3-5 items MOST worth their morning attention. For each: 1 sentence summary + 1 sentence on why it matters specifically for billetkit's operation. No filler. No "interesting!" / "amazing!" — concrete language.

Format strictly:

[1] <title> — <score>↑
    <url>
    — what it is: <one sentence>
    — why billetkit cares: <one sentence>

[2] ...

End with one closing line: a single tactical observation or anti-pattern to avoid based on the night's signal. No "let me know if you need more".

VOICE: lowercase first words OK. No emojis. No exclamation points. Dry, confident.
LENGTH: 250-400 words total."""

    user = f"""Tonight's top HN items (already filtered to AI/agent/indie relevant):

{chr(10).join(item_lines)}

Compose the intel brief now."""

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 1000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, headers={
            "x-api-key": auth_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, timeout=90)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"summarize error: {e}", flush=True)
        return None


def main():
    print(f"[hn-intel] starting at {datetime.datetime.now()}", flush=True)
    stories = fetch_top_stories(n=50)
    print(f"[hn-intel] fetched {len(stories)} top stories", flush=True)
    relevant = [(rank, item) for rank, item in stories if is_relevant(item)]
    print(f"[hn-intel] {len(relevant)} relevant after keyword filter", flush=True)

    secrets = load_secrets()
    if not relevant:
        intel = "No HN items overnight matched the agent/AI/indie-hacker filter. Either it was a quiet night or our keyword set is too narrow — worth reviewing the regex weekly."
    else:
        intel = summarize_via_sonnet(relevant, secrets)
        if not intel:
            # Fallback: raw list
            lines = []
            for rank, item in relevant[:5]:
                lines.append(f"[{rank}] {item.get('title')} ({item.get('score')}↑)")
                lines.append(f"    https://news.ycombinator.com/item?id={item.get('id')}")
            intel = "Sonnet summary failed. Raw top-5 relevant items:\n\n" + "\n".join(lines)

    # Persist to intel dir for historical reference
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    p = INTEL / f"hn-{today}.md"
    p.write_text(f"# HN intel · {today}\n\n_Generated {datetime.datetime.now().isoformat()}_\n\n{intel}\n")
    print(f"[hn-intel] wrote {p.name} ({len(intel)} chars)", flush=True)

    # Also drop into operator outbox if there's substance
    if relevant and intel and "matched the agent/AI" not in intel[:200]:
        ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
        out = MEMORY / "operator-outbox" / f"{ts}-hn-intel.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        header = f"📰 HN overnight · {today}\n\n"
        out.write_text(header + intel)
        print(f"[hn-intel] queued for Telegram: {out.name}", flush=True)


if __name__ == "__main__":
    main()
