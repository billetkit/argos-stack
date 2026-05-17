#!/usr/bin/env python3
"""dashboard.py — Futuristic live UI for the billetkit agent stack.

Runs on the Mac mini at http://argos-host:8080 (and http://192.168.7.103:8080
from your laptop). Auto-refreshes every 2s via Server-Sent Events.

Shows:
- Heartbeat status: last tick, next tick countdown, ticks today
- KPI: did a stranger pay today, current streak
- Sub-agent state: support / sales / memory — idle / drafting / acting
- Surfaces: ClawMart inbox, Bluesky/X mentions, reply queue, Stripe, intents
- Live log tail (last 20 heartbeat lines) — auto-scrolling
- System: uptime, RAM used/free, disk, Ollama model status
- Pending drafts queue (sales sub-agent outputs awaiting your approve/reject)

Usage:
    python3 dashboard.py        # foreground
    # Or installed as LaunchAgent via dashboard.plist
"""

import os, sys, json, time, pathlib, subprocess, threading, queue
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, render_template_string, request

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
HEARTBEAT_LOG = MEMORY / "heartbeat.log"
KPI_FILE = MEMORY / "kpi.md"
LAST_TICK = MEMORY / "last-tick.json"
DRAFTS_DIR = MEMORY / "drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# ---------- data gatherers ----------

def now_utc():
    return datetime.now(timezone.utc)


def read_log_tail(n=20):
    if not HEARTBEAT_LOG.exists():
        return []
    lines = HEARTBEAT_LOG.read_text().splitlines()[-n:]
    return lines


def heartbeat_state():
    """Parse the log tail to derive: last tick time, next tick countdown, today's tick count."""
    if not HEARTBEAT_LOG.exists():
        return {"last_tick_iso": None, "seconds_since_last": None, "next_tick_in_seconds": 900, "ticks_today": 0, "last_result": "unknown"}

    lines = HEARTBEAT_LOG.read_text().splitlines()
    today = now_utc().date().isoformat()
    ticks_today = sum(1 for l in lines if f"[{today}" in l and "heartbeat start" in l)

    # Find most recent "heartbeat start" — own loop, no early break
    last_start = None
    for l in reversed(lines):
        if "heartbeat start" in l:
            try:
                ts = l.split("[", 1)[1].split("]", 1)[0]
                last_start = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                pass
            break

    # Find most recent result (idle / working) — separate loop
    last_result = "unknown"
    for l in reversed(lines):
        low = l.lower()
        if "work found" in low:
            last_result = "working"; break
        if "idle. all surfaces" in low:
            last_result = "idle"; break

    # Heartbeat interval matches the LaunchAgent's StartInterval (currently 300s = 5 min)
    HEARTBEAT_INTERVAL = 300
    seconds_since = None
    next_tick = HEARTBEAT_INTERVAL
    if last_start:
        seconds_since = int((now_utc() - last_start).total_seconds())
        next_tick = max(0, HEARTBEAT_INTERVAL - seconds_since)

    return {
        "last_tick_iso": last_start.isoformat() if last_start else None,
        "seconds_since_last": seconds_since,
        "next_tick_in_seconds": next_tick,
        "ticks_today": ticks_today,
        "last_result": last_result,
    }


def kpi_state():
    """Parse kpi.md for today's row + current streak."""
    if not KPI_FILE.exists():
        return {"today_paid": False, "streak_no": 0, "streak_yes": 0}

    text = KPI_FILE.read_text()
    today = datetime.now().date().isoformat()
    today_paid = f"- {today}: stranger paid ✓" in text

    rows = [l for l in text.splitlines() if l.startswith("- ") and "stranger paid" in l]
    streak_no = streak_yes = 0
    for r in reversed(rows):
        if "✓" in r:
            if streak_no == 0:
                streak_yes += 1
            else:
                break
        else:
            if streak_yes == 0:
                streak_no += 1
            else:
                break

    return {"today_paid": today_paid, "streak_no": streak_no, "streak_yes": streak_yes}


def surfaces_state():
    """Last-tick counts per surface, from heartbeat log.
    Heartbeat logs `surfaces · k1=v1, k2=v2, ...` every tick."""
    if not HEARTBEAT_LOG.exists():
        return {}
    lines = HEARTBEAT_LOG.read_text().splitlines()
    for l in reversed(lines):
        if "surfaces ·" in l or "surfaces:" in l or "work found:" in l:
            sep = "surfaces ·" if "surfaces ·" in l else ("surfaces:" if "surfaces:" in l else "work found:")
            try:
                payload = l.split(sep, 1)[1].strip()
                parts = [p.strip() for p in payload.split(",")]
                return {k.strip(): int(v.strip()) for k, v in (p.split("=") for p in parts)}
            except Exception:
                pass
    return {}


def sub_agent_state():
    """Each sub-agent: status + last action."""
    agents = {}
    for name in ("support", "sales", "memory"):
        log_path = MEMORY / f"{name}-log.md"
        last_action = "never"
        status = "idle"
        if log_path.exists():
            lines = log_path.read_text().splitlines()
            if lines:
                # Look for last dated entry
                for l in reversed(lines):
                    if l.startswith("## "):
                        last_action = l[3:].strip()
                        break
        agents[name] = {"status": status, "last_action": last_action}
    return agents


def drafts_pending():
    """Drafts the sales sub-agent has prepared, awaiting operator approve/reject."""
    if not DRAFTS_DIR.exists():
        return []
    out = []
    for p in sorted(DRAFTS_DIR.glob("*.md"))[:10]:
        try:
            content = p.read_text()
            meta = {"id": p.stem, "preview": content[:200], "created": p.stat().st_mtime}
            out.append(meta)
        except Exception:
            pass
    return out


def system_state():
    """uptime + ram + disk + ollama models loaded"""
    try:
        uptime = subprocess.check_output(["uptime"], text=True).strip()
    except Exception:
        uptime = "?"

    try:
        # vm_stat for memory on macOS
        vm = subprocess.check_output(["vm_stat"], text=True)
        pagesize = 16384  # M-series default
        def pct(line):
            return int(line.split(":")[1].strip().rstrip(".")) * pagesize
        wired = active = free = inactive = compressed = 0
        for l in vm.splitlines():
            if "wired down" in l: wired = pct(l)
            elif "active" in l and "Pages active" in l: active = pct(l)
            elif "Pages free" in l: free = pct(l)
            elif "inactive" in l and "Pages inactive" in l: inactive = pct(l)
            elif "occupied by compressor" in l: compressed = pct(l)
        used_gb = round((wired + active + compressed) / (1024**3), 1)
        free_gb = round((free + inactive) / (1024**3), 1)
    except Exception:
        used_gb = free_gb = 0

    try:
        df = subprocess.check_output(["df", "-h", "/"], text=True).splitlines()[1].split()
        disk = f"{df[2]} / {df[3]}"
    except Exception:
        disk = "?"

    ollama_models = []
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
            ollama_models = [m.get("name") for m in data.get("models", [])]
    except Exception:
        pass

    return {
        "uptime": uptime,
        "ram_used_gb": used_gb,
        "ram_free_gb": free_gb,
        "disk": disk,
        "ollama_models": ollama_models,
    }


def gather_all():
    return {
        "ts": now_utc().isoformat(),
        "heartbeat": heartbeat_state(),
        "kpi": kpi_state(),
        "surfaces": surfaces_state(),
        "sub_agents": sub_agent_state(),
        "drafts": drafts_pending(),
        "system": system_state(),
        "log": read_log_tail(20),
    }


# ---------- routes ----------

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/state")
def state():
    return jsonify(gather_all())


@app.route("/api/stream")
def stream():
    def gen():
        while True:
            data = json.dumps(gather_all())
            yield f"data: {data}\n\n"
            time.sleep(2)
    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/draft/<draft_id>/approve", methods=["POST"])
def draft_approve(draft_id):
    p = DRAFTS_DIR / f"{draft_id}.md"
    if not p.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    # Move to approved/ for the sales sub-agent to publish
    approved = MEMORY / "approved"
    approved.mkdir(parents=True, exist_ok=True)
    p.rename(approved / p.name)
    return jsonify({"ok": True})


@app.route("/api/draft/<draft_id>/reject", methods=["POST"])
def draft_reject(draft_id):
    p = DRAFTS_DIR / f"{draft_id}.md"
    if not p.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    rejected = MEMORY / "rejected"
    rejected.mkdir(parents=True, exist_ok=True)
    p.rename(rejected / p.name)
    return jsonify({"ok": True})


# ---------- the UI ----------

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ARGOS · billetkit</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #06080d;
    --bg-alt: #0c1018;
    --bg-card: #0f1422;
    --border: #1a2138;
    --border-glow: #2d3a5c;
    --text: #d8dee9;
    --text-dim: #5b6577;
    --text-dimmer: #3a4258;
    --green: #00ff9f;
    --cyan: #00d4ff;
    --amber: #ffaa00;
    --red: #ff3366;
    --pink: #ff79c6;
    --purple: #a78bfa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--bg); color: var(--text); font-family: 'JetBrains Mono', monospace; font-weight: 400; min-height: 100vh; overflow-x: hidden; }
  body {
    background-image:
      linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
  }
  body::before {
    content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 100;
    background: linear-gradient(transparent 50%, rgba(0,0,0,0.04) 50%);
    background-size: 100% 3px;
    opacity: 0.6;
  }
  header {
    padding: 20px 32px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--border); background: linear-gradient(180deg, var(--bg-alt), transparent);
  }
  .brand { display: flex; align-items: center; gap: 14px; }
  .brand-logo { font-size: 22px; font-weight: 700; letter-spacing: 0.15em; color: var(--green); text-shadow: 0 0 12px rgba(0,255,159,0.5); }
  .brand-sub { color: var(--text-dim); font-size: 12px; letter-spacing: 0.2em; }
  .status-pill { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-dim); letter-spacing: 0.15em; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .timestamp { font-size: 12px; color: var(--text-dim); letter-spacing: 0.05em; }
  main { padding: 28px 32px; max-width: 1600px; margin: 0 auto; }
  .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 20px; }
  .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 4px; padding: 18px 20px; position: relative; overflow: hidden; }
  .card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, var(--border-glow), transparent); }
  .card-title { font-size: 10px; letter-spacing: 0.25em; color: var(--text-dim); margin-bottom: 14px; font-weight: 500; }
  .card-value { font-size: 28px; font-weight: 500; color: var(--text); margin-bottom: 4px; }
  .card-value.green { color: var(--green); text-shadow: 0 0 12px rgba(0,255,159,0.3); }
  .card-value.cyan { color: var(--cyan); text-shadow: 0 0 12px rgba(0,212,255,0.3); }
  .card-value.amber { color: var(--amber); text-shadow: 0 0 12px rgba(255,170,0,0.3); }
  .card-value.red { color: var(--red); }
  .card-value.dim { color: var(--text-dimmer); }
  .card-sub { font-size: 11px; color: var(--text-dim); letter-spacing: 0.05em; }
  .col-3 { grid-column: span 3; }
  .col-4 { grid-column: span 4; }
  .col-6 { grid-column: span 6; }
  .col-8 { grid-column: span 8; }
  .col-12 { grid-column: span 12; }
  .surfaces-list { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .surface-item { background: var(--bg); border: 1px solid var(--border); padding: 14px 16px; border-radius: 3px; transition: border-color 0.2s; }
  .surface-item:hover { border-color: var(--border-glow); }
  .surface-item.has-work { border-color: var(--amber); box-shadow: 0 0 16px rgba(255,170,0,0.15); }
  .surface-name { font-size: 9px; letter-spacing: 0.2em; color: var(--text-dim); margin-bottom: 6px; }
  .surface-count { font-size: 24px; font-weight: 500; color: var(--text); }
  .surface-count.zero { color: var(--text-dimmer); }
  .surface-count.nonzero { color: var(--amber); }
  .agents-list { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .agent-item { background: var(--bg); border-left: 2px solid var(--green); padding: 14px 16px; border-radius: 2px; }
  .agent-item.busy { border-left-color: var(--amber); }
  .agent-name { font-size: 11px; color: var(--text); letter-spacing: 0.15em; font-weight: 500; margin-bottom: 6px; }
  .agent-status { font-size: 10px; color: var(--text-dim); letter-spacing: 0.1em; margin-bottom: 8px; }
  .agent-last { font-size: 11px; color: var(--text-dimmer); }
  .log-container { background: var(--bg); border: 1px solid var(--border); border-radius: 3px; padding: 14px 16px; max-height: 320px; overflow-y: auto; font-size: 11px; line-height: 1.6; }
  .log-container::-webkit-scrollbar { width: 6px; }
  .log-container::-webkit-scrollbar-thumb { background: var(--border-glow); border-radius: 3px; }
  .log-line { color: var(--text-dim); display: block; padding: 2px 0; font-family: 'JetBrains Mono', monospace; }
  .log-line.fresh { color: var(--green); animation: fadein 0.4s; }
  @keyframes fadein { from { opacity: 0; transform: translateX(-4px); } to { opacity: 1; transform: translateX(0); } }
  .system-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; font-size: 11px; }
  .system-stat-label { color: var(--text-dim); letter-spacing: 0.1em; margin-bottom: 4px; font-size: 9px; }
  .system-stat-value { color: var(--text); font-size: 14px; }
  .draft-card { background: var(--bg); border: 1px solid var(--border); padding: 14px 16px; border-radius: 3px; margin-bottom: 10px; }
  .draft-meta { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 10px; color: var(--text-dim); letter-spacing: 0.1em; }
  .draft-preview { font-size: 12px; color: var(--text); margin-bottom: 12px; line-height: 1.5; max-height: 4.5em; overflow: hidden; }
  .draft-actions { display: flex; gap: 8px; }
  .btn { background: transparent; border: 1px solid var(--border); color: var(--text-dim); font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.15em; padding: 6px 12px; border-radius: 2px; cursor: pointer; transition: all 0.15s; }
  .btn:hover { border-color: var(--cyan); color: var(--cyan); }
  .btn.btn-approve:hover { border-color: var(--green); color: var(--green); box-shadow: 0 0 8px rgba(0,255,159,0.2); }
  .btn.btn-reject:hover { border-color: var(--red); color: var(--red); box-shadow: 0 0 8px rgba(255,51,102,0.2); }
  .empty { color: var(--text-dimmer); font-size: 11px; text-align: center; padding: 24px 0; letter-spacing: 0.05em; }
  .countdown { font-variant-numeric: tabular-nums; }
  footer { padding: 20px 32px; color: var(--text-dimmer); font-size: 10px; letter-spacing: 0.1em; text-align: center; border-top: 1px solid var(--border); margin-top: 32px; }

  /* --- ARGOS presence orb --- */
  .presence-card { display: flex; align-items: center; gap: 28px; padding: 24px 28px; min-height: 180px; background: linear-gradient(135deg, var(--bg-card) 0%, var(--bg-alt) 100%); }
  .orb-wrap { position: relative; width: 140px; height: 140px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
  .orb-core {
    width: 60px; height: 60px; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, var(--green) 0%, #00b873 50%, #006a42 100%);
    box-shadow: 0 0 24px var(--green), 0 0 60px rgba(0,255,159,0.3), inset 0 0 10px rgba(255,255,255,0.4);
    animation: orb-breathe 4s ease-in-out infinite;
    transition: background 0.6s ease, box-shadow 0.6s ease;
  }
  .orb-ring {
    position: absolute; border-radius: 50%; border: 1px solid var(--green);
    opacity: 0; animation: orb-ring-expand 4s ease-out infinite;
  }
  .orb-ring-1 { width: 80px; height: 80px; animation-delay: 0s; }
  .orb-ring-2 { width: 110px; height: 110px; animation-delay: 1s; }
  .orb-ring-3 { width: 140px; height: 140px; animation-delay: 2s; }
  @keyframes orb-breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); }
  }
  @keyframes orb-ring-expand {
    0% { transform: scale(0.5); opacity: 0.8; }
    100% { transform: scale(1.3); opacity: 0; }
  }
  /* State variants */
  .presence-card.state-thinking .orb-core {
    background: radial-gradient(circle at 35% 30%, var(--cyan) 0%, #0099cc 50%, #005577 100%);
    box-shadow: 0 0 32px var(--cyan), 0 0 80px rgba(0,212,255,0.4), inset 0 0 12px rgba(255,255,255,0.5);
    animation-duration: 1.2s;
  }
  .presence-card.state-thinking .orb-ring { border-color: var(--cyan); animation-duration: 1.2s; }
  .presence-card.state-work .orb-core {
    background: radial-gradient(circle at 35% 30%, var(--amber) 0%, #cc8800 50%, #774e00 100%);
    box-shadow: 0 0 28px var(--amber), 0 0 70px rgba(255,170,0,0.35), inset 0 0 12px rgba(255,255,255,0.4);
    animation-duration: 2s;
  }
  .presence-card.state-work .orb-ring { border-color: var(--amber); animation-duration: 2s; }
  .presence-card.state-recent-reply .orb-core {
    background: radial-gradient(circle at 35% 30%, var(--pink) 0%, #c44dad 50%, #6a2860 100%);
    box-shadow: 0 0 32px var(--pink), 0 0 80px rgba(255,121,198,0.4), inset 0 0 12px rgba(255,255,255,0.5);
    animation-duration: 1s;
  }
  .presence-card.state-recent-reply .orb-ring { border-color: var(--pink); animation-duration: 1s; }

  .presence-info { flex: 1; }
  .presence-name { font-size: 18px; font-weight: 700; letter-spacing: 0.2em; color: var(--text); margin-bottom: 4px; }
  .presence-handle { font-size: 11px; color: var(--text-dim); letter-spacing: 0.15em; margin-bottom: 16px; }
  .presence-state-label { font-size: 10px; letter-spacing: 0.25em; color: var(--text-dim); margin-bottom: 8px; }
  .presence-state-value { font-size: 14px; color: var(--green); letter-spacing: 0.1em; transition: color 0.4s; min-height: 20px; }
  .presence-card.state-thinking .presence-state-value { color: var(--cyan); }
  .presence-card.state-work .presence-state-value { color: var(--amber); }
  .presence-card.state-recent-reply .presence-state-value { color: var(--pink); }
  .presence-portrait-placeholder { font-size: 10px; color: var(--text-dimmer); letter-spacing: 0.15em; margin-top: 14px; padding: 8px 12px; border: 1px dashed var(--border-glow); border-radius: 3px; display: inline-block; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-logo">ARGOS</div>
    <div class="brand-sub">· billetkit · v2</div>
  </div>
  <div class="status-pill"><span class="dot"></span><span id="status-text">ONLINE</span></div>
  <div class="timestamp" id="timestamp">—</div>
</header>

<main>
  <div class="grid">
    <div class="card col-12 presence-card state-idle" id="presence">
      <div class="orb-wrap">
        <div class="orb-ring orb-ring-1"></div>
        <div class="orb-ring orb-ring-2"></div>
        <div class="orb-ring orb-ring-3"></div>
        <div class="orb-core"></div>
      </div>
      <div class="presence-info">
        <div class="presence-name">ARGOS</div>
        <div class="presence-handle">billetkit · sonnet 4.5 · phone link active</div>
        <div class="presence-state-label">CURRENT STATE</div>
        <div class="presence-state-value" id="presence-state-value">idle · watching surfaces</div>
      </div>
    </div>

    <div class="card col-3">
      <div class="card-title">HEARTBEAT</div>
      <div class="card-value green" id="hb-next">--:--</div>
      <div class="card-sub" id="hb-meta">awaiting first tick</div>
    </div>
    <div class="card col-3">
      <div class="card-title">KPI · $1 TODAY</div>
      <div class="card-value dim" id="kpi-val">NO</div>
      <div class="card-sub" id="kpi-meta">streak: —</div>
    </div>
    <div class="card col-3">
      <div class="card-title">TICKS TODAY</div>
      <div class="card-value cyan" id="ticks-val">0</div>
      <div class="card-sub" id="ticks-meta">last: —</div>
    </div>
    <div class="card col-3">
      <div class="card-title">MODEL</div>
      <div class="card-value cyan" id="model-val">—</div>
      <div class="card-sub" id="model-meta">—</div>
    </div>

    <div class="card col-12">
      <div class="card-title">SURFACES · LAST TICK</div>
      <div class="surfaces-list" id="surfaces">
        <div class="surface-item"><div class="surface-name">GITHUB ★</div><div class="surface-count zero" id="surf-github_stars">0</div></div>
        <div class="surface-item"><div class="surface-name">GITHUB ISSUES</div><div class="surface-count zero" id="surf-github_issues">0</div></div>
        <div class="surface-item"><div class="surface-name">CLAWMART INBOX</div><div class="surface-count zero" id="surf-clawmart_inbox">0</div></div>
        <div class="surface-item"><div class="surface-name">BLUESKY/X MENTIONS</div><div class="surface-count zero" id="surf-bluesky_mentions">0</div></div>
        <div class="surface-item"><div class="surface-name">REPLY QUEUE</div><div class="surface-count zero" id="surf-bluesky_reply_queue">0</div></div>
        <div class="surface-item"><div class="surface-name">STRIPE SALES</div><div class="surface-count zero" id="surf-stripe_new_sales">0</div></div>
        <div class="surface-item"><div class="surface-name">OPERATOR INBOX</div><div class="surface-count zero" id="surf-operator_inbox">0</div></div>
        <div class="surface-item"><div class="surface-name">INTENTS</div><div class="surface-count zero" id="surf-intents_pending">0</div></div>
      </div>
    </div>

    <div class="card col-6">
      <div class="card-title">SUB-AGENTS</div>
      <div class="agents-list" id="agents"></div>
    </div>

    <div class="card col-6">
      <div class="card-title">SYSTEM</div>
      <div class="system-grid" id="system"></div>
    </div>

    <div class="card col-12">
      <div class="card-title">LIVE LOG · HEARTBEAT</div>
      <div class="log-container" id="log"></div>
    </div>

    <div class="card col-12">
      <div class="card-title">DRAFTS · AWAITING APPROVAL</div>
      <div id="drafts"><div class="empty">no drafts pending — sub-agents are idle</div></div>
    </div>
  </div>
</main>

<footer>billetkit · 24/7 autonomous agent stack · live SSE · refresh every 2s</footer>

<script>
const $ = id => document.getElementById(id);
let lastLogLength = 0;

// Client-side live countdown: server gives us seconds-remaining,
// we decrement smoothly between SSE pushes.
let serverNextTick = 900;
let serverSecondsSince = null;
let lastServerUpdate = Date.now();

function fmt_countdown(s) {
  if (s == null) return '--:--';
  s = Math.max(0, Math.floor(s));
  const m = Math.floor(s / 60), sec = s % 60;
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}
function fmt_ago(s) {
  if (s == null) return '—';
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s/60)}m ago`;
}

function liveTick() {
  const elapsed = (Date.now() - lastServerUpdate) / 1000;
  $('hb-next').textContent = fmt_countdown(serverNextTick - elapsed);
  if (serverSecondsSince != null) {
    $('hb-meta').textContent = `last tick ${fmt_ago(Math.floor(serverSecondsSince + elapsed))} · ${$('hb-meta').dataset.result || 'idle'}`;
  }
}
setInterval(liveTick, 1000);

function render(state) {
  $('timestamp').textContent = new Date(state.ts).toLocaleTimeString();
  // heartbeat — sync the live ticker baseline
  serverNextTick = state.heartbeat.next_tick_in_seconds;
  serverSecondsSince = state.heartbeat.seconds_since_last;
  lastServerUpdate = Date.now();
  $('hb-next').textContent = fmt_countdown(state.heartbeat.next_tick_in_seconds);
  $('hb-meta').dataset.result = state.heartbeat.last_result;
  $('hb-meta').textContent = `last tick ${fmt_ago(state.heartbeat.seconds_since_last)} · ${state.heartbeat.last_result}`;
  $('ticks-val').textContent = state.heartbeat.ticks_today;
  $('ticks-meta').textContent = state.heartbeat.last_tick_iso ? `last ${new Date(state.heartbeat.last_tick_iso).toLocaleTimeString()}` : 'none yet';

  // kpi
  const kpi = $('kpi-val');
  kpi.textContent = state.kpi.today_paid ? 'YES' : 'NO';
  kpi.className = 'card-value ' + (state.kpi.today_paid ? 'green' : 'dim');
  $('kpi-meta').textContent = state.kpi.today_paid ?
    `streak: ${state.kpi.streak_yes} day(s) paid` :
    `streak: ${state.kpi.streak_no} day(s) no`;

  // model
  if (state.system.ollama_models && state.system.ollama_models.length) {
    const driver = state.system.ollama_models.find(m => m.includes('32b-fast')) || state.system.ollama_models[0];
    $('model-val').textContent = driver.replace('qwen2.5-coder:', 'qwen·');
    $('model-meta').textContent = `${state.system.ollama_models.length} models loaded`;
  } else {
    $('model-val').textContent = 'OFFLINE';
    $('model-meta').textContent = 'ollama unreachable';
  }

  // surfaces
  ['github_stars','github_issues','clawmart_inbox','bluesky_mentions','bluesky_reply_queue','stripe_new_sales','operator_inbox','intents_pending'].forEach(k => {
    const el = $('surf-' + k);
    const count = state.surfaces[k] ?? 0;
    el.textContent = count;
    el.className = 'surface-count ' + (count > 0 ? 'nonzero' : 'zero');
    el.parentElement.className = 'surface-item' + (count > 0 ? ' has-work' : '');
  });

  // agents
  const agentsHTML = Object.entries(state.sub_agents).map(([name, a]) =>
    `<div class="agent-item ${a.status === 'busy' ? 'busy' : ''}">
       <div class="agent-name">${name.toUpperCase()}</div>
       <div class="agent-status">● ${a.status}</div>
       <div class="agent-last">last: ${a.last_action}</div>
     </div>`).join('');
  $('agents').innerHTML = agentsHTML;

  // system
  const sys = state.system;
  $('system').innerHTML = `
    <div><div class="system-stat-label">UPTIME</div><div class="system-stat-value">${(sys.uptime.match(/up\s+(.+?),/) || [,'?'])[1]}</div></div>
    <div><div class="system-stat-label">RAM USED</div><div class="system-stat-value">${sys.ram_used_gb} GB</div></div>
    <div><div class="system-stat-label">RAM FREE</div><div class="system-stat-value">${sys.ram_free_gb} GB</div></div>
    <div><div class="system-stat-label">DISK</div><div class="system-stat-value">${sys.disk}</div></div>
  `;

  // log
  const logBox = $('log');
  const wasAtBottom = (logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight) < 50;
  const isNew = state.log.length !== lastLogLength;
  logBox.innerHTML = state.log.map((line, i) => {
    const fresh = isNew && i >= lastLogLength ? 'fresh' : '';
    return `<span class="log-line ${fresh}">${line}</span>`;
  }).join('');
  lastLogLength = state.log.length;
  if (wasAtBottom) logBox.scrollTop = logBox.scrollHeight;

  // presence orb — derive state from data
  const presence = $('presence');
  const stateValue = $('presence-state-value');
  let presenceState = 'idle';
  let presenceMsg = 'idle · watching surfaces';

  const surfaces = state.surfaces || {};
  const hasWork = Object.values(surfaces).some(v => v > 0);
  const justRanTick = state.heartbeat.seconds_since_last != null && state.heartbeat.seconds_since_last < 15;
  const draftsCount = (state.drafts || []).length;

  if (justRanTick) {
    presenceState = 'thinking';
    presenceMsg = 'heartbeat just fired · checking surfaces';
  } else if (draftsCount > 0) {
    presenceState = 'recent-reply';
    presenceMsg = `${draftsCount} draft${draftsCount > 1 ? 's' : ''} ready for review`;
  } else if (hasWork) {
    presenceState = 'work';
    const items = Object.entries(surfaces).filter(([k,v]) => v > 0).map(([k,v]) => `${k.replace(/_/g,' ')}=${v}`).join(', ');
    presenceMsg = `work pending · ${items}`;
  }
  presence.className = 'card col-12 presence-card state-' + presenceState;
  stateValue.textContent = presenceMsg;

  // drafts
  const drafts = state.drafts || [];
  if (drafts.length === 0) {
    $('drafts').innerHTML = '<div class="empty">no drafts pending — sub-agents are idle</div>';
  } else {
    $('drafts').innerHTML = drafts.map(d => `
      <div class="draft-card">
        <div class="draft-meta"><span>${d.id}</span><span>${new Date(d.created*1000).toLocaleTimeString()}</span></div>
        <div class="draft-preview">${d.preview.replace(/</g,'&lt;')}</div>
        <div class="draft-actions">
          <button class="btn btn-approve" onclick="approveDraft('${d.id}')">▸ APPROVE</button>
          <button class="btn btn-reject" onclick="rejectDraft('${d.id}')">✕ REJECT</button>
        </div>
      </div>`).join('');
  }
}

async function approveDraft(id) {
  await fetch(`/api/draft/${id}/approve`, {method: 'POST'});
}
async function rejectDraft(id) {
  await fetch(`/api/draft/${id}/reject`, {method: 'POST'});
}

const evt = new EventSource('/api/stream');
evt.onmessage = e => {
  try { render(JSON.parse(e.data)); } catch (err) { console.error(err); }
};
evt.onerror = () => {
  $('status-text').textContent = 'RECONNECTING';
  document.querySelector('.dot').style.background = 'var(--amber)';
};
evt.onopen = () => {
  $('status-text').textContent = 'ONLINE';
  document.querySelector('.dot').style.background = 'var(--green)';
};

// initial fetch
fetch('/api/state').then(r => r.json()).then(render);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("ARGOS_DASHBOARD_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
