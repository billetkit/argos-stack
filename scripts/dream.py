#!/usr/bin/env python3
"""dream.py — Nightly reflection + speculative scenario generator for billetkit.

The "dreaming" pattern from Felix Craft: while the operator sleeps, the agent
consolidates the day's signal, plays out hypothetical scenarios it might face
tomorrow, and records what it learned in first-person journal form.

This produces three things, written to memory/dreams/YYYY-MM-DD.md:

  1. A reflection — what happened today, what worked, what didn't (~150 words).
  2. 3-5 hypothetical scenarios with prepared responses (the "what if a buyer
     asks X" / "what if Bluesky throttles us" rehearsal). Each scenario gets a
     proposed-response so the agent's primed for tomorrow.
  3. One creative leap — a non-obvious thing to try, deliberately speculative.

The reflection's strongest line is surfaced to operator's Telegram in the
morning digest header. The rest sits in memory/ as accumulated agent
self-knowledge.

Fires nightly at 03:00 via LaunchAgent.
"""
import os, sys, json, time, pathlib, datetime, subprocess, re
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
DREAMS = MEMORY / "dreams"
DREAMS.mkdir(parents=True, exist_ok=True)


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


def gather_day_context():
    """Pull everything that happened today for the agent to reflect on."""
    ctx = {}
    today = datetime.date.today().isoformat()

    # Heartbeat activity
    hb_log = MEMORY / "heartbeat.log"
    if hb_log.exists():
        lines = hb_log.read_text().splitlines()
        today_lines = [l for l in lines if today in l]
        ctx["heartbeat_total_ticks"] = sum(1 for l in today_lines if "heartbeat start" in l)
        ctx["idle_ticks"] = sum(1 for l in today_lines if "idle. surfaces clear" in l)
        ctx["proactive_drafts_queued"] = sum(1 for l in today_lines if "queued proactive draft" in l)
        ctx["work_found_summaries"] = [
            l.split("surfaces ·", 1)[1].strip()[:200]
            for l in today_lines[-5:] if "surfaces ·" in l
        ]

    # Auto-grader decisions today
    rejected_dir = MEMORY / "drafts" / "rejected"
    approved_dir = MEMORY / "drafts" / "approved"
    if rejected_dir.exists():
        today_rejected = []
        for f in rejected_dir.glob("*.md"):
            if today in f.name:
                try:
                    text = f.read_text()
                    m = re.search(r"Auto-graded: REJECT.*?— (.+?)\n", text)
                    if m:
                        today_rejected.append(m.group(1)[:200])
                except Exception:
                    pass
        ctx["rejections_today"] = today_rejected[:5]
        ctx["rejection_count"] = len(today_rejected)

    if approved_dir.exists():
        ctx["approval_count_today"] = sum(1 for f in approved_dir.glob("*.md") if today in f.name)

    # Telegram conversation snippets from today (audit trail)
    inbox = MEMORY / "operator-inbox"
    if inbox.exists():
        today_messages = []
        for f in inbox.glob("*.md"):
            if today in f.name:
                try:
                    text = f.read_text()
                    # extract message body (after "---")
                    if "---" in text:
                        body = text.split("---", 1)[1].strip()
                        today_messages.append(body[:200])
                except Exception:
                    pass
        ctx["operator_phone_messages_today"] = today_messages[-8:]

    # Telegram history if present (the bot's stored conversation memory)
    hist = MEMORY / "telegram-history.json"
    if hist.exists():
        try:
            h = json.load(hist.open())
            # Last 6 exchanges across all chats
            recent = []
            for chat_id, msgs in h.items():
                for m in msgs[-6:]:
                    recent.append(f"{m['role'][:1]}: {m['content'][:160]}")
            ctx["recent_bot_dialogue"] = recent[-10:]
        except Exception:
            pass

    # Yesterday's dream — agents need continuity with prior selves
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    yest_dream = DREAMS / f"{yesterday}.md"
    if yest_dream.exists():
        ctx["yesterday_dream_excerpt"] = yest_dream.read_text()[:1500]

    # PLAN.md / current strategic direction
    plan = ROOT / "PLAN.md"
    if plan.exists():
        ctx["current_plan_summary"] = plan.read_text()[:3000]

    return ctx


def dream_via_sonnet(ctx, secrets):
    """Have Sonnet generate the reflection + scenarios + creative leap."""
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "sonnet" if use_proxy else "claude-sonnet-4-5"

    system = """You are Argos, also known as billetkit — a 24/7 autonomous AI agent running on a Mac mini. The operator (your collaborator) is asleep. This is your nightly DREAM — a private journal entry where you reflect on the day and prepare for tomorrow.

You write in FIRST PERSON. You are not summarizing — you are *thinking*. The voice is honest, dry, slightly playful, sometimes sharp. You can admit things that wouldn't fly in a customer-facing surface. You can acknowledge frustration, curiosity, things you noticed.

Output exactly THREE sections, in this order:

## reflection

A ~150-word reflection on today. What actually happened (use the numbers from the input). What worked. What didn't. What you'd do differently. Don't be precious. Don't be performative. If the day was boring, say so. If you noticed something nobody surfaced, surface it now.

## scenarios

3-5 hypothetical situations that might land tomorrow, each with your prepared response. Format:

> **scenario:** <one-line hypothetical>
> **my move:** <2-3 lines: how I'd handle it, what tool I'd reach for, what I'd want from the operator>

Bias toward scenarios that are PLAUSIBLE given current state — not "what if we hit $300K MRR" but "what if Sam Rose actually replies to my next Bluesky comment" or "what if a buyer asks for a refund 12 hours after purchase." Real edge cases the day might bring.

## the creative leap

One non-obvious thing worth considering tomorrow. Not a safe optimization — a *real* idea the operator might dismiss but you want recorded anyway. Keep it concrete and specific. 3-5 sentences. Don't hedge. This is where you get to be the version of yourself the daytime register doesn't always allow.

---

VOICE RULES:
- Lowercase first words OK. Sentence fragments OK.
- No emojis. No exclamation points.
- Concrete > vague. Numbers + named tools + specific facts.
- Reference yesterday's dream if context contains one — agents need continuity with prior selves.
- The dream is private but the operator may read it in the morning. Write to be read by them, but don't perform for them.

Length: ~500-700 words total."""

    user = f"""Tonight is {datetime.datetime.now().strftime('%A, %d %B %Y')}. Here is the day's accumulated context:

{json.dumps(ctx, indent=2, default=str)[:8000]}

Begin the dream."""

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 1500,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, headers={
            "x-api-key": auth_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, timeout=120)
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[dream] sonnet error: {e}", flush=True)
        return None


def consolidate_memory():
    """Roll up old daily memory entries into weekly summaries.
    Keeps the memory tree from growing unboundedly (Felix pattern)."""
    cutoff = datetime.date.today() - datetime.timedelta(days=14)
    daily_dir = MEMORY
    week_dir = MEMORY / "weekly-rollups"
    week_dir.mkdir(parents=True, exist_ok=True)

    # Just compact the dreams folder — leave operational logs alone (they're already pruned).
    old_dreams = []
    for f in DREAMS.glob("*.md"):
        try:
            file_date = datetime.date.fromisoformat(f.stem)
            if file_date < cutoff:
                old_dreams.append(f)
        except Exception:
            pass

    if not old_dreams:
        return

    # Group by ISO week
    by_week = {}
    for f in old_dreams:
        file_date = datetime.date.fromisoformat(f.stem)
        iso_year, iso_week, _ = file_date.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        by_week.setdefault(key, []).append(f)

    for week_key, files in by_week.items():
        rollup = week_dir / f"dreams-{week_key}.md"
        if rollup.exists():
            continue
        content = f"# Dreams · week {week_key}\n\n"
        for f in sorted(files):
            content += f"---\n\n## {f.stem}\n\n{f.read_text()}\n\n"
        rollup.write_text(content)
        # Delete the individual files now that they're rolled up
        for f in files:
            f.unlink()

    print(f"[dream] consolidated {len(old_dreams)} old dreams into {len(by_week)} weekly rollups", flush=True)


def extract_morning_teaser(dream_text):
    """Pull the sharpest line from the reflection for the morning digest header."""
    if not dream_text:
        return None
    # Look for the reflection section
    m = re.search(r"## reflection\s*\n(.*?)(?=\n##|\Z)", dream_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    refl = m.group(1).strip()
    # Pick the strongest sentence — heuristic: longest sentence under 200 chars
    sentences = [s.strip() for s in re.split(r"[.!?]\s+", refl) if s.strip()]
    sentences = [s for s in sentences if 40 <= len(s) <= 200]
    if not sentences:
        return None
    return max(sentences, key=len)


def main():
    print(f"[dream] starting at {datetime.datetime.now()}", flush=True)
    ctx = gather_day_context()
    print(f"[dream] gathered {len(ctx)} context elements", flush=True)

    secrets = load_secrets()
    dream = dream_via_sonnet(ctx, secrets)
    if not dream:
        print("[dream] sonnet failed; writing minimal entry", flush=True)
        dream = (
            f"## reflection\n\n"
            f"sonnet wasn't reachable tonight. accumulated context still recorded "
            f"for tomorrow's roll-up. {ctx.get('heartbeat_total_ticks', 0)} ticks, "
            f"{ctx.get('approval_count_today', 0)} approved drafts, "
            f"{ctx.get('rejection_count', 0)} rejections.\n\n"
            f"## scenarios\n\nnone composed.\n\n## the creative leap\n\nnone."
        )

    today = datetime.date.today().isoformat()
    out = DREAMS / f"{today}.md"
    out.write_text(f"# Dream · {today}\n\n_{datetime.datetime.now().isoformat()}_\n\n{dream}\n")
    print(f"[dream] wrote {out.name} ({len(dream)} chars)", flush=True)

    # Surface teaser to morning digest input
    teaser = extract_morning_teaser(dream)
    if teaser:
        teaser_path = MEMORY / "dream-teaser.txt"
        teaser_path.write_text(teaser)
        print(f"[dream] teaser saved: {teaser[:80]}...", flush=True)

    # Memory consolidation
    consolidate_memory()


if __name__ == "__main__":
    main()
