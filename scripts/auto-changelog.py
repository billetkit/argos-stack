#!/usr/bin/env python3
"""auto-changelog.py — Nightly self-documenting CHANGELOG for billetkit/argos-stack.

Reads git log since yesterday, summarizes via Haiku (cheap classification task),
appends to CHANGELOG.md, commits + pushes. Public-facing legitimacy artifact.

Fires nightly at 04:00 local via LaunchAgent.
"""
import os, sys, json, time, pathlib, datetime, subprocess
import requests

REPO_DIR = pathlib.Path("/tmp/argos-stack")
CHANGELOG_PATH = REPO_DIR / "CHANGELOG.md"

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"


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


def run(cmd, cwd=None):
    return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def pull_repo(secrets):
    """Ensure local clone exists and is current."""
    pat = secrets.get("BILLETKIT_GITHUB_PAT")
    if not pat:
        raise RuntimeError("BILLETKIT_GITHUB_PAT not in secrets.env")
    url = f"https://billetkit:{pat}@github.com/billetkit/argos-stack.git"

    if REPO_DIR.exists():
        run(["git", "fetch", "origin"], cwd=str(REPO_DIR))
        run(["git", "reset", "--hard", "origin/main"], cwd=str(REPO_DIR))
    else:
        run(["git", "clone", url, str(REPO_DIR)])
        run(["git", "config", "user.email", "billetkit@proton.me"], cwd=str(REPO_DIR))
        run(["git", "config", "user.name", "billetkit"], cwd=str(REPO_DIR))


def get_recent_log(hours=24):
    """Return git log entries from the last N hours, plus shortstat diffs."""
    since = f"{hours} hours ago"
    try:
        log = run(
            ["git", "log", f"--since={since}", "--pretty=format:%h %s", "--shortstat"],
            cwd=str(REPO_DIR),
        )
        return log
    except subprocess.CalledProcessError:
        return ""


def summarize_via_haiku(log_text, secrets):
    """Have Haiku turn raw git log into a 4-8 bullet CHANGELOG entry in billetkit voice."""
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "haiku" if use_proxy else "claude-haiku-4-5"

    system = """You write CHANGELOG entries for billetkit/argos-stack, an autonomous AI agent stack on GitHub. Given raw git log entries from the last 24 hours, produce a clean CHANGELOG block.

FORMAT (strict):

## YYYY-MM-DD

- <change in past tense, 6-15 words, focused on user/operator impact, not implementation details>
- <change>
- ...

VOICE:
- Lowercase first word of each bullet OK
- No emojis. No exclamation points.
- Concrete: "added FLUX dev to img-server" beats "added new image generation features"
- Skip merge commits and pure refactors. Bias toward changes that actually shipped capability or fixed a real issue.
- Maximum 8 bullets even if the log is huge. Pick the most-impact ones.
- If no meaningful changes, output exactly: ## YYYY-MM-DD\n\n- no shipped changes this cycle\n

Don't editorialize. Don't add headers beyond the date. Don't add a closing line."""

    user = f"""Date: {datetime.date.today().isoformat()}

Recent git log:

{log_text}

Compose the CHANGELOG block now."""

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 800,
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
        print(f"haiku error: {e}", flush=True)
        return None


def upsert_changelog(new_block):
    """Prepend the new block to CHANGELOG.md, creating the file if missing."""
    today = datetime.date.today().isoformat()
    header = f"# Changelog\n\nAuto-generated nightly by `auto-changelog.py`. Newest first.\n\n"

    existing = ""
    if CHANGELOG_PATH.exists():
        existing = CHANGELOG_PATH.read_text()
        # Strip the static header from existing to re-add cleanly
        if existing.startswith(header):
            existing = existing[len(header):]
        # If today's entry already there, replace it instead of duplicating
        if f"## {today}" in existing:
            # Cut from "## today" to next "## " or end
            import re
            existing = re.sub(rf"## {today}.*?(?=\n## |\Z)", "", existing, flags=re.DOTALL).strip()

    CHANGELOG_PATH.write_text(header + new_block.strip() + "\n\n" + existing.strip() + "\n")


def commit_and_push():
    """Commit the changelog change and push to origin/main."""
    try:
        status = run(["git", "status", "--porcelain"], cwd=str(REPO_DIR))
        if not status.strip():
            print("[auto-changelog] no changes to commit", flush=True)
            return False
        run(["git", "add", "CHANGELOG.md"], cwd=str(REPO_DIR))
        run(["git", "commit", "-m", f"changelog: auto-update for {datetime.date.today().isoformat()}"], cwd=str(REPO_DIR))
        run(["git", "push", "origin", "main"], cwd=str(REPO_DIR))
        return True
    except subprocess.CalledProcessError as e:
        print(f"[auto-changelog] git error: {e.output if hasattr(e, 'output') else e}", flush=True)
        return False


def main():
    print(f"[auto-changelog] starting at {datetime.datetime.now()}", flush=True)
    secrets = load_secrets()
    pull_repo(secrets)
    log_text = get_recent_log(hours=24)
    if not log_text.strip():
        print("[auto-changelog] no commits in last 24h, skipping", flush=True)
        return

    print(f"[auto-changelog] log size: {len(log_text)} chars, summarizing via Haiku...", flush=True)
    block = summarize_via_haiku(log_text, secrets)
    if not block:
        print("[auto-changelog] haiku failed; falling back to raw log", flush=True)
        block = f"## {datetime.date.today().isoformat()}\n\n```\n{log_text[:2000]}\n```\n"

    upsert_changelog(block)
    pushed = commit_and_push()
    print(f"[auto-changelog] {'pushed' if pushed else 'no push needed'}", flush=True)


if __name__ == "__main__":
    main()
