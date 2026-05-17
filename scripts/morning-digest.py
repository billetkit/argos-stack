#!/usr/bin/env python3
"""morning-digest.py — Compose a tight overnight summary and push it to operator's phone.

Fires once daily via LaunchAgent (StartCalendarInterval). Reads:
  - heartbeat log (tick count, idle/work)
  - drafts state (approved / rejected / pending)
  - kpi.md (paid today / streak)
  - Langfuse trace count + latest model used
  - GitHub stars on billetkit/argos-stack
  - system metrics (uptime, memory, disk)

Sends to Sonnet for a 200-word digest in billetkit voice, then writes the result
to v2/memory/operator-outbox/ — telegram-bot drains the outbox and pushes to phone
within 2s.
"""

import os, sys, json, time, pathlib, datetime, subprocess, re
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
DRAFTS = MEMORY / "drafts"
OUTBOX = MEMORY / "operator-outbox"
OUTBOX.mkdir(parents=True, exist_ok=True)


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


def gather_inputs():
    """Pull everything we need for the digest."""
    s = {}
    # Heartbeat ticks since UTC midnight
    today_utc = datetime.datetime.now(datetime.UTC).date().isoformat()
    hb_log = MEMORY / "heartbeat.log"
    if hb_log.exists():
        lines = hb_log.read_text().splitlines()
        today_lines = [l for l in lines if today_utc in l]
        s["heartbeat_ticks_today"] = sum(1 for l in today_lines if "heartbeat start" in l)
        s["idle_ticks"] = sum(1 for l in today_lines if "idle. surfaces clear" in l)
        s["work_ticks"] = sum(1 for l in today_lines if "queued proactive draft" in l)
        # Most recent surface snapshot
        for l in reversed(today_lines):
            if "surfaces ·" in l:
                s["last_surface_snapshot"] = l.split("surfaces ·", 1)[1].strip()[:200]
                break

    # Drafts state
    if DRAFTS.exists():
        s["drafts_pending"] = len(list(DRAFTS.glob("*.md")))
        approved_dir = DRAFTS / "approved"
        rejected_dir = DRAFTS / "rejected"
        s["drafts_approved_total"] = len(list(approved_dir.glob("*.md"))) if approved_dir.exists() else 0
        s["drafts_rejected_total"] = len(list(rejected_dir.glob("*.md"))) if rejected_dir.exists() else 0
        # Sample one rejection reason
        if rejected_dir.exists():
            recent = sorted(rejected_dir.glob("*.md"))[-3:]
            reasons = []
            for f in recent:
                try:
                    text = f.read_text()
                    m = re.search(r"Auto-graded: REJECT.*?— (.+?)\n", text)
                    if m:
                        reasons.append(m.group(1)[:150])
                except Exception:
                    pass
            if reasons:
                s["recent_rejection_reasons"] = reasons

    # KPI
    kpi = MEMORY / "kpi.md"
    if kpi.exists():
        s["kpi_tail"] = "\n".join(kpi.read_text().splitlines()[-5:])

    # Langfuse trace count + latest model
    secrets = load_secrets()
    pub = secrets.get("LANGFUSE_PUBLIC_KEY")
    sec = secrets.get("LANGFUSE_SECRET_KEY")
    if pub and sec:
        try:
            r = requests.get(
                "http://localhost:3000/api/public/traces",
                params={"limit": 5},
                auth=(pub, sec), timeout=5,
            )
            if r.status_code == 200:
                d = r.json()
                s["langfuse_total_traces"] = d.get("meta", {}).get("totalItems", 0)
                if d.get("data"):
                    s["latest_trace_at"] = (d["data"][0].get("timestamp") or "")[:19]
        except Exception:
            pass

    # GitHub stars on argos-stack
    pat = secrets.get("BILLETKIT_GITHUB_PAT")
    if pat:
        try:
            r = requests.get(
                "https://api.github.com/repos/billetkit/argos-stack",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
                timeout=5,
            )
            if r.status_code == 200:
                d = r.json()
                s["github_stars"] = d.get("stargazers_count", 0)
                s["github_forks"] = d.get("forks_count", 0)
                s["github_open_issues"] = d.get("open_issues_count", 0)
        except Exception:
            pass

    # System
    try:
        uptime = subprocess.check_output(["uptime"], text=True).strip()
        s["uptime_line"] = uptime
    except Exception:
        pass

    # Disk
    try:
        df = subprocess.check_output(["df", "-h", "/"], text=True).splitlines()[1].split()
        s["disk_used_free"] = f"{df[2]} used / {df[3]} free"
    except Exception:
        pass

    # LiteLLM today's spend (if we can read its DB or estimate from trace count)
    # For now: rough estimate from trace count (~$0.005/Sonnet + $0.0006/Haiku avg)
    if s.get("langfuse_total_traces"):
        s["est_daily_spend_usd"] = round(s["langfuse_total_traces"] * 0.003, 4)

    return s


def compose_via_sonnet(inputs, secrets):
    """Have Sonnet write the digest in voice."""
    api_key = secrets.get("ANTHROPIC_API_KEY")
    master_key = secrets.get("LITELLM_MASTER_KEY")
    if not api_key:
        return None

    use_proxy = bool(master_key)
    endpoint = "http://localhost:4000/v1/messages" if use_proxy else "https://api.anthropic.com/v1/messages"
    auth_key = master_key if use_proxy else api_key
    model = "sonnet" if use_proxy else "claude-sonnet-4-5"

    system = """You are Argos / billetkit composing a morning digest for your operator. They read this on their phone over coffee.

VOICE RULES (strict):
- 150-220 words, no more
- Lowercase first words fine. No exclamation points. No emojis (the operator dislikes them in digest format).
- Lead with the most interesting/highest-signal item, not "good morning" or filler
- Concrete numbers > vague adjectives. Numbers should come from the input data, never invented.
- Mention 1 thing that's interesting or worth their attention today (not just stats)
- Close with one pointed observation or recommendation — what should they actually look at today
- Confident, dry, slightly playful. No "let me know if you need anything" closers.

OUTPUT FORMAT: plain text, no markdown headers, no bullet lists unless genuinely necessary."""

    user = f"""Overnight inputs as of {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} local:

{json.dumps(inputs, indent=2)}

Write the digest now."""

    try:
        r = requests.post(endpoint, json={
            "model": model,
            "max_tokens": 600,
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
        print(f"compose error: {e}", flush=True)
        return None


def main():
    print(f"[morning-digest] starting at {datetime.datetime.now()}", flush=True)
    inputs = gather_inputs()
    print(f"[morning-digest] gathered {len(inputs)} signals", flush=True)
    secrets = load_secrets()
    digest = compose_via_sonnet(inputs, secrets)
    if not digest:
        digest = (
            f"morning. heartbeat fired {inputs.get('heartbeat_ticks_today', '?')} times overnight. "
            f"drafts pending {inputs.get('drafts_pending', 0)}, "
            f"approved {inputs.get('drafts_approved_total', 0)}, "
            f"rejected {inputs.get('drafts_rejected_total', 0)}. "
            f"langfuse traces today {inputs.get('langfuse_total_traces', 0)}. "
            f"github stars {inputs.get('github_stars', 0)}. "
            f"(sonnet digest composer failed — this is the raw fallback)"
        )

    # Write to outbox — telegram-bot drains and sends within 2s
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
    out_path = OUTBOX / f"{ts}-morning-digest.md"
    header = f"☀ morning digest · {datetime.datetime.now().strftime('%a %d %b %H:%M')}\n\n"
    out_path.write_text(header + digest)
    print(f"[morning-digest] wrote {out_path.name} ({len(digest)} chars)", flush=True)


if __name__ == "__main__":
    main()
