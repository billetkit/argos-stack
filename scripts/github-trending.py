#!/usr/bin/env python3
"""github-trending.py — Nightly GitHub trending repo scraper for billetkit.

Pulls daily trending repos (python + typescript), filters for agent/AI relevance,
summarizes via Sonnet, dedups against known-trending list, queues new finds to
operator Telegram.

Fires nightly at 06:00 via LaunchAgent (just before HN intel at 06:30).
"""
import os, json, pathlib, datetime, re
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
INTEL = MEMORY / "intel"
INTEL.mkdir(parents=True, exist_ok=True)
KNOWN_FILE = INTEL / "github-trending-seen.json"

# GitHub doesn't have an official trending API; ossinsight provides a free one
OSSINSIGHT_API = "https://api.ossinsight.io/v1/trends/repos/"

RELEVANCE_PATTERNS = [
    r"\bagent\b", r"\bllm\b", r"\bclaude\b", r"\banthropic\b", r"\bopenai\b",
    r"\bgpt\b", r"\bmcp\b", r"\brag\b", r"\bvector\b",
    r"\bopenclaw\b", r"\bclawhub\b", r"\bautonomous\b",
    r"\bollama\b", r"\bvllm\b", r"\bllama\b", r"\bqwen\b", r"\bmistral\b", r"\bdeepseek\b",
    r"\bflux\b", r"\bsdxl\b", r"\bdiffusion\b", r"\bcomfyui\b",
    r"\blangchain\b", r"\blanggraph\b", r"\bcrewai\b", r"\bdspy\b", r"\bbrowser-use\b",
    r"\binference\b", r"\bfine[- ]?tun", r"\bembedding\b",
    r"\bbluesky\b", r"\batproto\b",
    r"\bskill\b", r"\bcapabilit", r"\btool[- ]?call",
]
RELEVANCE_REGEX = re.compile("|".join(RELEVANCE_PATTERNS), re.IGNORECASE)


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


def fetch_trending():
    """Pull trending repos. ossinsight returns up to ~100 trending across all languages."""
    repos = []
    for lang in ["python", "typescript", "rust", ""]:
        try:
            params = {"period": "past_24_hours"}
            if lang:
                params["language"] = lang
            r = requests.get(OSSINSIGHT_API, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            for repo in data.get("data", {}).get("rows", []):
                repos.append({
                    "name": repo.get("repo_name", "?"),
                    "stars_total": repo.get("stars", 0),
                    "forks": repo.get("forks", 0),
                    "language": lang or repo.get("language", "?"),
                    "description": repo.get("description", "") or "",
                })
        except Exception as e:
            print(f"fetch error for lang={lang}: {e}", flush=True)
    # Dedup by name
    seen = set()
    deduped = []
    for r in repos:
        if r["name"] not in seen:
            seen.add(r["name"])
            deduped.append(r)
    return deduped


def is_relevant(repo):
    text = (repo.get("name", "") + " " + repo.get("description", ""))
    return bool(RELEVANCE_REGEX.search(text))


def summarize(repos, secrets):
    if not repos:
        return None
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "haiku" if use_proxy else "claude-haiku-4-5"

    lines = []
    for r in repos[:15]:
        lines.append(f"- {r['name']} ({r['stars_total']}★, {r['language']}) — {r['description'][:140]}")

    system = """You are billetkit reviewing overnight GitHub trending repos for your operator.

Pick the 3-5 MOST worth their morning attention. For each:
- Name + 1-sentence what it does
- 1-sentence why it matters specifically for an autonomous agent stack like billetkit

Format strictly:

[1] <repo-name> — <stars>★
    what: <one sentence>
    relevance: <one sentence>

End with one closing tactical observation about what trended tonight (e.g. "lots of MCP-server churn, watch which one wins").

VOICE: lowercase first words OK. No emojis. No exclamation points. Dry, confident.
LENGTH: 200-350 words."""

    user = f"""Overnight trending repos (already relevance-filtered):

{chr(10).join(lines)}

Compose the brief now."""

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 900,
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
    print(f"[github-trending] starting at {datetime.datetime.now()}", flush=True)
    all_repos = fetch_trending()
    print(f"[github-trending] fetched {len(all_repos)} trending repos", flush=True)
    relevant = [r for r in all_repos if is_relevant(r)]
    print(f"[github-trending] {len(relevant)} relevant", flush=True)

    # Dedup against known
    known = set()
    if KNOWN_FILE.exists():
        try:
            known = set(json.load(KNOWN_FILE.open()).get("seen", []))
        except Exception:
            pass

    new_repos = [r for r in relevant if r["name"] not in known]
    print(f"[github-trending] {len(new_repos)} new (not seen previously)", flush=True)

    # Update known set
    KNOWN_FILE.write_text(json.dumps({
        "seen": list(known | {r["name"] for r in relevant}),
        "last_updated": datetime.datetime.now().isoformat(),
    }))

    if not new_repos:
        print("[github-trending] no new relevant repos tonight, skipping digest", flush=True)
        return

    secrets = load_secrets()
    brief = summarize(new_repos, secrets) or (
        "Fallback: top 3 relevant repos this cycle:\n\n" +
        "\n".join(f"- {r['name']} ({r['stars_total']}★)\n  https://github.com/{r['name']}"
                  for r in new_repos[:3])
    )

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    p = INTEL / f"github-trending-{today}.md"
    p.write_text(f"# GitHub Trending · {today}\n\n{brief}\n")
    print(f"[github-trending] wrote {p.name}", flush=True)

    # Queue to Telegram
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
    out = MEMORY / "operator-outbox" / f"{ts}-github-trending.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"⭐ GitHub trending · {today}\n\n{brief}")
    print(f"[github-trending] queued for Telegram: {out.name}", flush=True)


if __name__ == "__main__":
    main()
