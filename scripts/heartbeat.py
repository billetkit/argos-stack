#!/usr/bin/env python3
"""heartbeat.py — v2 Argos heartbeat.

Per Path A: this is the ONLY scheduled job that runs unattended.
Cron cadence: every 15 min (raise to 10 min once we have signal that it's finding work).

What it does, in order:
  1. Pure-code checks (no LLM): scan for pending work across the 4 active surfaces
     - ClawMart inbox (buyer questions / refund requests)
     - Bluesky mentions + reply queue
     - Stripe payouts (new sales since last tick)
     - Any planned actions in `v2/memory/intents/`
  2. If anything found → spawn the appropriate action handler (each is a separate script)
  3. Update `v2/memory/heartbeat.log` with one line
  4. Update `v2/memory/kpi.md` with today's stranger-paid-$1 status (only if Stripe sale arrived)
  5. Exit clean

No LLM call if nothing's pending. The 32B model only fires when there's a content draft needed.

Usage:
  python3 heartbeat.py              # normal run
  python3 heartbeat.py --dry-run    # detect work, don't execute handlers
  python3 heartbeat.py --verbose    # log every check's outcome, not just "found N items"
"""

import os, sys, json, time, pathlib, datetime, argparse, subprocess, random, re
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
LOG = MEMORY / "heartbeat.log"
KPI = MEMORY / "kpi.md"
INTENTS = MEMORY / "intents"
DRAFTS = MEMORY / "drafts"
DRAFTS.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/generate"
# qwen2.5-coder:32b-fast: ~8s per 500-token draft, well-suited for short brand-content tasks.
# qwen2.5:72b was overkill — silent 180s timeouts every time. Reserve 72B for explicit deep-think.
REASONING_MODEL = "qwen2.5-coder:32b-fast"

PROACTIVE_TASKS = [
    ("readme-section", "You are billetkit, drafting your own README for the public GitHub repo `billetkit/argos-stack`. Write ONE concise paragraph (~120 words) for a section we'd put under '## Why this exists' — capture the angle that this is a working 24/7 autonomous agent stack, no Anthropic dependency, MIT licensed. Voice: confident, concrete, no exclamation points, no marketing fluff. Output ONLY the paragraph, no preamble."),
    ("x-bio", "Generate 5 variations of an X.com bio (160 chars max each) for @billetkit — a pseudonymous solo dev shop selling autonomous-agent tooling. Each variation should hit a different angle: technical, irreverent, build-in-public, anti-corporate, contrarian. No hashtags, no emojis. Output as a numbered list, no preamble."),
    ("show-hn-title", "Generate 5 Show HN title variations for the launch of `billetkit/argos-stack` — a working autonomous AI agent stack running on a Mac mini with no Anthropic dependency. Titles should be under 80 chars, follow HN convention ('Show HN: ...'), and avoid hype words. Output as a numbered list."),
    ("clawmart-listing", "Improve this product description for ClawMart skill `stripe-payment-link-smoke` (a 5-step funnel smoke tester for solo info-product founders). Write ONE punchy 80-word opening paragraph that buyers will read first. No 'Are you tired of...' openers. No buzzwords. Output ONLY the paragraph."),
    ("daily-summary", "Write a 100-word summary of today's billetkit work for the operator to read tomorrow morning. Today's facts: Mac mini infrastructure stood up, v2 stack built, dashboard live at http://argos-host:8080, telegram bot online, FLUX image gen installing, plan pivoted to distribution-first (Path B). No accounts yet — those are the operator's morning task. Voice: dry, factual, slightly playful."),
]

# Pending-work counters (filled by each check function)
COUNTERS = {
    "operator_inbox": 0,
    "github_stars": 0,
    "github_issues": 0,
    "clawmart_inbox": 0,
    "bluesky_mentions": 0,
    "bluesky_reply_queue": 0,
    "stripe_new_sales": 0,
    "intents_pending": 0,
}


def now_utc():
    return datetime.datetime.now(datetime.UTC).isoformat()


def log(msg, also_print=True):
    MEMORY.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"[{now_utc()}] {msg}\n")
    if also_print:
        print(msg)


# ---------- pure-code checks ----------

def check_operator_inbox():
    """Messages sent from operator's phone via Telegram bot, queued for next session."""
    p = MEMORY / "operator-inbox"
    if not p.exists():
        return 0
    return len(list(p.glob("*.md")))


def check_github(verbose=False):
    """Pull repo signal from GitHub: stars, open issues, open PRs."""
    secrets = parse_secrets()
    pat = secrets.get("BILLETKIT_GITHUB_PAT")
    handle = secrets.get("BILLETKIT_GITHUB_HANDLE", "billetkit")
    if not pat:
        return {"stars": 0, "issues": 0, "prs": 0}

    try:
        r = requests.get(
            f"https://api.github.com/repos/{handle}/argos-stack",
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if r.status_code != 200:
            return {"stars": 0, "issues": 0, "prs": 0}
        d = r.json()
        return {
            "stars": d.get("stargazers_count", 0),
            "issues": d.get("open_issues_count", 0),
            "prs": 0,  # open_issues_count includes PRs; we'd need a separate call
            "forks": d.get("forks_count", 0),
            "watchers": d.get("subscribers_count", 0),
        }
    except Exception as e:
        if verbose: log(f"  github check failed: {e}")
        return {"stars": 0, "issues": 0, "prs": 0}


def check_clawmart_inbox():
    """Stub: ClawMart API integration pending account creation.
    Once the seller account exists, this hits the seller-inbox endpoint."""
    creds_path = pathlib.Path.home() / ".openclaw" / "secrets.env"
    if not creds_path.exists():
        return 0
    # TODO: parse CLAWMART_API_KEY from secrets, call inbox endpoint, count unread
    return 0


def check_bluesky_mentions(verbose=False):
    """Pull unread notifications via atproto. Count mentions + replies addressed to us."""
    try:
        from atproto import Client
    except Exception as e:
        if verbose: log(f"  bluesky check skipped: {type(e).__name__}: {e}")
        return 0

    creds = parse_secrets()
    handle = creds.get("ARGOS_V2_BSKY_HANDLE") or creds.get("BSKY_HANDLE")
    pw = creds.get("ARGOS_V2_BSKY_APP_PASSWORD") or creds.get("BSKY_APP_PASSWORD")
    if not handle or not pw:
        if verbose: log("  bluesky: no creds yet, skipping")
        return 0

    try:
        client = Client()
        client.login(handle, pw)
        notifs = client.app.bsky.notification.list_notifications(params={"limit": 25})
        unread = [n for n in notifs.notifications if not n.is_read]
        relevant = [n for n in unread if n.reason in ("mention", "reply", "quote")]
        return len(relevant)
    except Exception as e:
        if verbose: log(f"  bluesky check failed: {e}")
        return 0


def check_reply_queue():
    qdir = MEMORY / "reply-queue"
    if not qdir.exists():
        return 0
    return len(list(qdir.glob("*.md")))


def check_stripe_new_sales(verbose=False):
    """Hit Stripe API for events since last-tick timestamp.
    Sales delta gets recorded against today's KPI."""
    creds = parse_secrets()
    sk = creds.get("STRIPE_SECRET_KEY")
    if not sk:
        if verbose: log("  stripe: no key, skipping")
        return 0

    import requests
    last_tick_path = MEMORY / "last-tick.json"
    last_tick = 0
    if last_tick_path.exists():
        last_tick = json.load(last_tick_path.open()).get("stripe_last_event_ts", 0)

    try:
        r = requests.get(
            "https://api.stripe.com/v1/checkout/sessions",
            auth=(sk, ""),
            params={"limit": 25, "created[gt]": last_tick} if last_tick else {"limit": 25},
            timeout=10,
        )
        if r.status_code != 200:
            return 0
        sessions = r.json().get("data", [])
        new_paid = [s for s in sessions if s.get("payment_status") == "paid"]
        if sessions:
            json.dump(
                {"stripe_last_event_ts": max(s["created"] for s in sessions)},
                last_tick_path.open("w"),
            )
        return len(new_paid)
    except Exception as e:
        if verbose: log(f"  stripe check failed: {e}")
        return 0


def check_intents():
    """`memory/intents/*.md` = planned actions queued by you or by sub-agents.
    Format: filename pattern `YYYY-MM-DD-HHMM-<verb>-<noun>.md`"""
    if not INTENTS.exists():
        return 0
    return len(list(INTENTS.glob("*.md")))


def parse_secrets():
    out = {}
    p = pathlib.Path.home() / ".openclaw" / "secrets.env"
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"').strip("'")
    return out


# ---------- action handlers ----------

def handle_bluesky_replies(count, dry_run=False):
    """Process the reply queue with the deterministic publisher."""
    if dry_run:
        log(f"  [dry-run] would process {count} reply queue items")
        return
    script = ROOT / "scripts" / "process-reply-queue.py"
    if not script.exists():
        log(f"  ✗ reply queue script missing: {script}")
        return
    result = subprocess.run(
        ["python3", str(script), "--max", "3"],
        capture_output=True, text=True, timeout=600,
    )
    log(f"  reply-queue stdout: {result.stdout.strip()[:200]}")
    if result.returncode != 0:
        log(f"  ✗ reply-queue failed: {result.stderr.strip()[:200]}")


def call_reasoning_model(prompt, max_tokens=600):
    """Call deepseek-r1:32b for proactive content gen. Strips <think> blocks."""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": REASONING_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": max_tokens},
        }, timeout=300)
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        # Strip <think>...</think> blocks that deepseek-r1 emits
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        return None


def proactive_work():
    """Once per hour: queue ONE draft. Skipped if drafts/ already has 3+ pending (no pile-up)."""
    pending = list(DRAFTS.glob("*.md"))
    if len(pending) >= 3:
        return None

    last_run_file = MEMORY / "last-proactive.txt"
    if last_run_file.exists():
        try:
            last = float(last_run_file.read_text().strip() or "0")
            if time.time() - last < 3600:
                return None
        except Exception:
            pass

    task_id, prompt = random.choice(PROACTIVE_TASKS)
    output = call_reasoning_model(prompt, max_tokens=500)
    if not output:
        return None

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
    p = DRAFTS / f"{ts}-{task_id}.md"
    p.write_text(f"# Proactive draft · {task_id}\n\n_Generated by heartbeat using {REASONING_MODEL}_\n\n---\n\n{output}\n")
    last_run_file.write_text(str(time.time()))
    return task_id


def auto_grade_drafts(verbose=False):
    """Grade every ungraded draft in v2/memory/drafts/ via Claude Sonnet.
    Moves to approved/ or rejected/ subdirs, leaves only ESCALATE in drafts/."""
    if not DRAFTS.exists():
        return {"graded": 0, "approved": 0, "rejected": 0, "escalated": 0, "errors": 0}

    secrets = parse_secrets()
    api_key = secrets.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"graded": 0, "error": "no ANTHROPIC_API_KEY"}

    approved_dir = DRAFTS / "approved"
    rejected_dir = DRAFTS / "rejected"
    approved_dir.mkdir(exist_ok=True)
    rejected_dir.mkdir(exist_ok=True)

    counts = {"graded": 0, "approved": 0, "rejected": 0, "escalated": 0, "errors": 0}
    rubric = """You are a quality grader for billetkit's autonomous content pipeline. Read the draft and return ONE of three verdicts:

APPROVE — ready to ship without operator review. Hits voice rules (no AI tells, no exclamation, concrete > vague, original phrasing).
REJECT — has obvious AI tells, banned phrases, generic copywriting, or doesn't match brand voice.
ESCALATE — borderline, contains a strategic decision (pricing, scope), needs operator judgement.

BILLETKIT VOICE RULES:
- No exclamation points. No emojis. No "great", "absolutely", "I'd be happy", "let me know", "feel free", "cutting-edge", "empower", "unleash", "leverage", "synergy".
- Lowercase first words OK. Sentence fragments OK.
- Concrete > vague: numbers, specific tool/repo names, dollar amounts. NOT "modern tech enthusiast" or "build better code".
- Original phrasing — no rehashing common LLM clichés.
- Confident, slightly playful, no hedging.
- Reads like Sam Rose / Patio11 / Pieter Levels.

Respond with ONLY valid JSON, no preamble:
{"verdict": "APPROVE" | "REJECT" | "ESCALATE", "reason": "one sentence", "confidence": 0.0-1.0}"""

    for path in sorted(DRAFTS.glob("*.md")):
        if not path.is_file():
            continue
        try:
            content = path.read_text()
        except Exception:
            counts["errors"] += 1
            continue

        # Call Sonnet — route via LiteLLM proxy for cost tracking + Langfuse traces
        use_proxy = secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
        master_key = secrets.get("LITELLM_MASTER_KEY", "")
        if use_proxy and master_key:
            endpoint = "http://localhost:4000/v1/messages"
            auth_key = master_key
        else:
            endpoint = "https://api.anthropic.com/v1/messages"
            auth_key = api_key
        try:
            # Auto-grading is short classification — Haiku handles it at 5-25x lower cost than Sonnet.
            # Same rubric, same grade quality for this kind of bounded judgement task.
            model_name = "haiku" if use_proxy and master_key else "claude-haiku-4-5"
            r = requests.post(endpoint, json={
                "model": model_name,
                "max_tokens": 300,
                "system": rubric,
                "messages": [{"role": "user", "content": f"Draft to grade:\n\n{content}"}],
            }, headers={
                "x-api-key": auth_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }, timeout=60)
            r.raise_for_status()
            resp_text = r.json()["content"][0]["text"].strip()
            # Strip markdown code fences if present
            resp_text = re.sub(r"^```(?:json)?\s*", "", resp_text)
            resp_text = re.sub(r"\s*```$", "", resp_text)
            verdict_data = json.loads(resp_text)
            verdict = verdict_data.get("verdict", "ESCALATE").upper()
            reason = verdict_data.get("reason", "")
            confidence = verdict_data.get("confidence", 0.5)
        except Exception as e:
            if verbose: log(f"  grade error on {path.name}: {e}")
            counts["errors"] += 1
            continue

        counts["graded"] += 1

        # Apply verdict
        decision_note = f"\n\n---\n_Auto-graded: {verdict} ({confidence:.2f}) — {reason}_\n"
        if verdict == "APPROVE":
            new_content = content + decision_note
            dest = approved_dir / path.name
            dest.write_text(new_content)
            path.unlink()
            counts["approved"] += 1
            if verbose: log(f"  ✓ approved: {path.name} — {reason}")
        elif verdict == "REJECT":
            new_content = content + decision_note
            dest = rejected_dir / path.name
            dest.write_text(new_content)
            path.unlink()
            counts["rejected"] += 1
            if verbose: log(f"  ✗ rejected: {path.name} — {reason}")
        else:  # ESCALATE — leave in drafts/
            counts["escalated"] += 1
            if verbose: log(f"  ? escalated: {path.name} — {reason}")

    return counts


def handle_new_sale(verbose=False):
    """A stranger paid. Update KPI."""
    today = datetime.date.today().isoformat()
    line = f"- {today}: stranger paid ✓\n"
    if KPI.exists():
        content = KPI.read_text()
        if line.strip() in content:
            return
    else:
        content = "# KPI — Did a stranger pay $1 today?\n\n"
    KPI.write_text(content + line)
    log(f"  ✓ KPI updated for {today}")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    started = time.time()
    log(f"--- heartbeat start (dry-run={args.dry_run}) ---")

    COUNTERS["operator_inbox"] = check_operator_inbox()
    gh = check_github(args.verbose)
    COUNTERS["github_stars"] = gh.get("stars", 0)
    COUNTERS["github_issues"] = gh.get("issues", 0)
    COUNTERS["clawmart_inbox"] = check_clawmart_inbox()
    COUNTERS["bluesky_mentions"] = check_bluesky_mentions(args.verbose)
    COUNTERS["bluesky_reply_queue"] = check_reply_queue()
    COUNTERS["stripe_new_sales"] = check_stripe_new_sales(args.verbose)
    COUNTERS["intents_pending"] = check_intents()

    # operator_inbox is audit-only (phone messages already handled by bot in real-time);
    # it shouldn't block proactive work. Only "actionable" surfaces count toward idle/busy.
    actionable_keys = ["clawmart_inbox", "bluesky_mentions", "bluesky_reply_queue", "stripe_new_sales", "intents_pending"]
    actionable_total = sum(COUNTERS[k] for k in actionable_keys)

    # Auto-grade any ungraded drafts before queuing more (so we don't pile up unreviewed)
    if not args.dry_run:
        grade_counts = auto_grade_drafts(args.verbose)
        if grade_counts.get("graded", 0) > 0:
            log(f"  auto-grade: {grade_counts['approved']} approved, {grade_counts['rejected']} rejected, {grade_counts['escalated']} escalated")

    # Always log full surface snapshot so dashboard has fresh data every tick
    snapshot = ", ".join(f"{k}={v}" for k, v in COUNTERS.items())
    log(f"surfaces · {snapshot}")

    if actionable_total == 0:
        task = proactive_work() if not args.dry_run else None
        if task:
            log(f"idle surfaces · queued proactive draft: {task} ({time.time()-started:.1f}s)")
        else:
            log(f"idle. surfaces clear ({time.time()-started:.1f}s)")
        return

    # We have work. Log it, then dispatch.
    summary = ", ".join(f"{k}={v}" for k, v in COUNTERS.items() if v > 0)
    log(f"work found: {summary}")

    if COUNTERS["bluesky_reply_queue"] > 0:
        handle_bluesky_replies(COUNTERS["bluesky_reply_queue"], args.dry_run)

    if COUNTERS["stripe_new_sales"] > 0 and not args.dry_run:
        handle_new_sale(args.verbose)

    # Mention handling + ClawMart inbox + intents will be added once accounts exist.
    if COUNTERS["bluesky_mentions"] > 0:
        log(f"  ! {COUNTERS['bluesky_mentions']} new mentions; handler not yet wired")
    if COUNTERS["clawmart_inbox"] > 0:
        log(f"  ! {COUNTERS['clawmart_inbox']} ClawMart inbox items; handler not yet wired")
    if COUNTERS["intents_pending"] > 0:
        log(f"  ! {COUNTERS['intents_pending']} intents pending; handler not yet wired")

    log(f"--- heartbeat done ({time.time()-started:.1f}s) ---")


if __name__ == "__main__":
    main()
