#!/usr/bin/env python3
"""dream.py — Canonical OpenClaw dreaming sweep (light → REM → deep).

This implements the documented OpenClaw 2026.4.5+ dreaming protocol exactly as
specified in https://docs.openclaw.ai/concepts/dreaming. Three phases run in
order during a nightly sweep at 03:00 local:

  LIGHT — ingest recent daily signals, dedupe, stage candidates (non-durable).
           Happens implicitly as the agent works via heartbeat — populates
           ~/argos/memory/.dreams/short-term-recall.json.

  REM   — extract patterns and reflective signals. Writes ## REM Sleep block
           to DREAMS.md via `openclaw memory rem-backfill`. Non-durable.

  DEEP  — rank candidates with weighted scoring (frequency 0.24, relevance 0.30,
           query diversity 0.15, recency 0.15, consolidation 0.10, conceptual
           richness 0.06), promote top to MEMORY.md via `openclaw memory promote --apply`.
           Durable.

After the canonical phases, this also adds Nat Eliason's "Layer 2 → Layer 1"
extraction pattern: pulls today's operator-inbox messages + heartbeat surface
summary into ~/argos/memory/daily-notes/YYYY-MM-DD.md so the next sweep has
fresh Layer 2 content to consolidate.

Fires nightly at 03:00 via LaunchAgent (StartCalendarInterval).
"""
import os, sys, json, time, pathlib, datetime, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
DAILY_NOTES = MEMORY / "daily-notes"
DAILY_NOTES.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[dream {datetime.datetime.now().isoformat()}] {msg}", flush=True)


def run_openclaw(args, timeout=180):
    """Invoke openclaw CLI, capture output."""
    cmd = ["/opt/homebrew/bin/openclaw"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": r.returncode == 0,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "exit_code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def write_daily_note():
    """Build today's daily note (Layer 2 in Nat Eliason's architecture).
    Captures: phone messages received, heartbeat activity summary, draft pipeline state,
    KPI for the day. The next dreaming sweep extracts the durable parts into MEMORY.md.
    """
    today = datetime.date.today().isoformat()
    note_path = DAILY_NOTES / f"{today}.md"
    sections = [f"# Daily note · {today}\n"]

    # Operator phone messages
    inbox = MEMORY / "operator-inbox"
    archive = inbox / "archive"
    today_msgs = []
    for d in [inbox, archive]:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            if today in f.name:
                try:
                    text = f.read_text()
                    if "---" in text:
                        body = text.split("---", 1)[1].strip()
                        today_msgs.append(body)
                except Exception:
                    pass

    if today_msgs:
        sections.append("## Operator messages today\n")
        for m in today_msgs[-20:]:
            sections.append(f"- {m[:300]}")
        sections.append("")

    # Heartbeat activity summary
    hb_log = MEMORY / "heartbeat.log"
    if hb_log.exists():
        lines = hb_log.read_text().splitlines()
        today_lines = [l for l in lines if today in l]
        ticks = sum(1 for l in today_lines if "heartbeat start" in l)
        idle = sum(1 for l in today_lines if "idle. surfaces clear" in l)
        proactive = sum(1 for l in today_lines if "queued proactive draft" in l)
        sections.append(f"## Heartbeat\n\n- ticks: {ticks}\n- idle ticks: {idle}\n- proactive drafts queued: {proactive}\n")

    # Drafts pipeline state today
    rej_dir = MEMORY / "drafts" / "rejected"
    app_dir = MEMORY / "drafts" / "approved"
    rej_today = sum(1 for f in rej_dir.glob("*.md") if today in f.name) if rej_dir.exists() else 0
    app_today = sum(1 for f in app_dir.glob("*.md") if today in f.name) if app_dir.exists() else 0
    sections.append(f"## Drafts\n\n- approved: {app_today}\n- rejected: {rej_today}\n")

    # KPI
    kpi = MEMORY / "kpi.md"
    if kpi.exists():
        kpi_lines = kpi.read_text().splitlines()
        today_kpi = [l for l in kpi_lines if today in l]
        if today_kpi:
            sections.append(f"## KPI today\n\n" + "\n".join(today_kpi) + "\n")

    note_path.write_text("\n".join(sections))
    log(f"wrote daily note: {note_path.name} ({note_path.stat().st_size} bytes)")


def main():
    log("=== canonical OpenClaw dreaming sweep starting ===")

    # Phase 0: reindex (so dreaming sees fresh content)
    log("phase 0: reindex memory")
    r = run_openclaw(["memory", "index"], timeout=300)
    if r["ok"]:
        log(f"  indexed: {r['stdout'].strip()[:200]}")
    else:
        log(f"  reindex error: {r.get('stderr', r.get('error', ''))[:200]}")

    # Write today's daily note (Nat's Layer 2)
    log("writing today's daily note (Layer 2)")
    write_daily_note()

    # Phase 1: LIGHT is implicit (heartbeat populates short-term-recall.json continuously)

    # Phase 2: REM — extract reflective signals across each workspace, write to DREAMS.md
    log("phase 2: REM — rem-backfill across workspaces into DREAMS.md")
    workspaces = [str(ROOT.parent), str(ROOT.parent / "sub-agents" / "support"),
                  str(ROOT.parent / "sub-agents" / "sales"),
                  str(ROOT.parent / "sub-agents" / "memory")]
    for ws in workspaces:
        if not pathlib.Path(ws).exists():
            continue
        r = run_openclaw(["memory", "rem-backfill", "--path", ws], timeout=300)
        if r["ok"]:
            log(f"  REM ({ws}): {r['stdout'].strip()[:150]}")
        else:
            err = (r.get('stderr') or r.get('error') or '')[:150]
            if err and "requires" not in err:
                log(f"  REM ({ws}) skipped: {err}")

    # Phase 3: DEEP — promote ranked candidates to MEMORY.md (durable)
    log("phase 3: DEEP — promote --apply")
    r = run_openclaw(["memory", "promote", "--apply"], timeout=300)
    if r["ok"]:
        log(f"  DEEP done: {r['stdout'].strip()[:300]}")
    else:
        log(f"  DEEP error: {(r.get('stderr') or r.get('error') or '')[:300]}")

    # Status report
    log("post-sweep status:")
    r = run_openclaw(["memory", "status"], timeout=60)
    for line in r.get("stdout", "").splitlines():
        if any(k in line for k in ["Recall store", "Dreaming:", "promoted", "diary", "files ·"]):
            log(f"  {line.strip()}")

    log("=== sweep complete ===")


if __name__ == "__main__":
    main()
