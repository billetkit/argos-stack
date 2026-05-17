#!/usr/bin/env python3
"""telegram-bot.py — Real-time operator phone ⇄ Argos relay.

Architecture (v2 — real-time, not deferred):
  - Long-polls Telegram getUpdates with 25s timeout (effectively push-based)
  - Each authorized message:
      1. Append to v2/memory/operator-inbox/{ts}-{msg_id}.md (audit trail)
      2. Build context: system prompt + Argos state + per-chat history
      3. Call local Ollama (qwen2.5-coder:32b-fast by default)
      4. Send response back via Telegram immediately
      5. Persist conversation history per chat_id
  - When the Anthropic quota returns (post 2026-06-01), set ROUTE_TO_API=true
    and the bot can hit the Anthropic API instead — same protocol, real Claude.

Required env (from ~/.openclaw/secrets.env):
  BILLETKIT_BOT_TOKEN          — from @BotFather
  BILLETKIT_BOT_CHAT_ID        — operator's own chat id (set after /start)
  BILLETKIT_BOT_MODEL          — optional, default qwen2.5-coder:32b-fast
  BILLETKIT_BOT_ROUTE_TO_API   — optional, "true" to use Anthropic
  ANTHROPIC_API_KEY            — only needed if ROUTE_TO_API=true
"""

import os, json, time, pathlib, datetime, sys, traceback, subprocess, re, shlex
import requests

# ---------- TOOL DEFINITIONS (sent to Anthropic API on each call) ----------

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a shell command on the Mac mini (argos-host). Returns stdout, stderr, exit_code. Use for: checking system state, running osascript, opening URLs in Safari on the TV, querying ollama, manipulating files in ~/argos/, curl tests, etc. Blocked: rm -rf, sudo, dd, shutdown, fork bombs, chmod 777, mv at filesystem root, curl|sh patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout_seconds": {"type": "integer", "description": "Max execution time, default 30, capped at 60", "default": 30}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from the mini. Restricted to ~/argos/, ~/.openclaw/, /tmp/. Returns content (truncated to max_bytes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 50000}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write/overwrite a file. Restricted to ~/argos/v2/memory/, ~/argos/v2/docs/drafts/, /tmp/. CANNOT write to scripts, configs, or system locations — those changes go through a Claude Code laptop session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "osascript",
        "description": "Run AppleScript on the mini. Useful for `display dialog`, `display notification`, `open <url>` analogs. Renders to the TV that's connected via HDMI. AppleScript that controls Safari/Mail/etc requires TCC permission which hasn't been granted, so prefer `display dialog` / `display notification` / `do shell script` patterns over `tell application X` controllers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "AppleScript source (the part you'd pass to osascript -e)"}
            },
            "required": ["script"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the live web via Tavily. Use for: looking up news/docs/announcements newer than your training cutoff, fact-checking claims, finding recent GitHub repos or HN posts, verifying URLs work, researching a specific question the operator asks. Returns top results with snippets. Don't use for filesystem questions or things you can answer from PLAN.md / CAPABILITIES.md.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query — be specific, include year/date keywords when freshness matters"},
                "max_results": {"type": "integer", "description": "Number of results to return, default 5, max 10", "default": 5},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "basic=faster/cheaper, advanced=deeper crawl. Default basic.", "default": "basic"}
            },
            "required": ["query"]
        }
    },
]

DENY_PATTERNS = [
    r"\brm\s+-r[fF]?\b",
    r"\bsudo\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # classic fork bomb
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bmv\s+/[^~]",  # mv at filesystem root (but allow ~ paths)
    r"\bchmod\s+(\d*7\d*|[ugoa]?\+rwx)",
    r">\s*/dev/(sd|hd|nvme|disk)",
    r"curl\s+[^|]*\|\s*(bash|sh|zsh)",  # remote-script execution
    r"wget\s+[^|]*\|\s*(bash|sh|zsh)",
]

ALLOW_READ_PREFIXES = [
    os.path.expanduser("~/argos/"),
    os.path.expanduser("~/.openclaw/"),  # for config inspection
    "/tmp/",
]

ALLOW_WRITE_PREFIXES = [
    os.path.expanduser("~/argos/v2/memory/"),
    os.path.expanduser("~/argos/v2/docs/drafts/"),
    "/tmp/",
]


def run_bash(command, timeout=30):
    """Execute bash command with safety filter. Returns dict."""
    for pat in DENY_PATTERNS:
        if re.search(pat, command):
            return {"ok": False, "error": f"command rejected by safety filter (matched: {pat})", "command": command[:200]}
    timeout = min(max(int(timeout), 1), 60)
    try:
        r = subprocess.run(
            ["/bin/bash", "-c", command],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.expanduser("~/argos"),
        )
        return {
            "ok": True,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-1000:],
            "exit_code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def read_file_safe(path, max_bytes=50000):
    """Read a file from an allowed prefix."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not any(abs_path.startswith(p) for p in ALLOW_READ_PREFIXES):
        return {"ok": False, "error": f"path {abs_path} not in allowed read prefixes: {ALLOW_READ_PREFIXES}"}
    try:
        with open(abs_path, "r", errors="replace") as f:
            content = f.read(max_bytes + 1)
        truncated = len(content) > max_bytes
        return {"ok": True, "content": content[:max_bytes], "truncated": truncated}
    except FileNotFoundError:
        return {"ok": False, "error": f"not found: {abs_path}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def write_file_safe(path, content):
    """Write a file under an allowed prefix. Creates parent dirs."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not any(abs_path.startswith(p) for p in ALLOW_WRITE_PREFIXES):
        return {"ok": False, "error": f"path {abs_path} not in allowed write prefixes: {ALLOW_WRITE_PREFIXES}"}
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(content)
        return {"ok": True, "path": abs_path, "bytes": len(content)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run_web_search(query, max_results=5, search_depth="basic"):
    """Tavily web search. Returns ranked results with snippets."""
    secrets = load_secrets()
    api_key = secrets.get("TAVILY_API_KEY")
    if not api_key:
        return {"ok": False, "error": "TAVILY_API_KEY not configured"}
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": min(int(max_results or 5), 10),
                "search_depth": search_depth if search_depth in ("basic", "advanced") else "basic",
                "include_answer": True,
                "include_raw_content": False,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        # Compact the results so they fit in tool_result without blowing context
        results = []
        for item in data.get("results", [])[:int(max_results or 5)]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:600],
                "score": item.get("score"),
            })
        return {
            "ok": True,
            "answer": data.get("answer"),  # Tavily's synthesized answer if available
            "results": results,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run_osascript(script):
    """Run AppleScript via osascript -e."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "ok": r.returncode == 0,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip(),
            "exit_code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "osascript timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def handle_tool_call(name, input_obj):
    """Dispatch a tool call from the API."""
    try:
        if name == "bash":
            return run_bash(input_obj["command"], input_obj.get("timeout_seconds", 30))
        elif name == "read_file":
            return read_file_safe(input_obj["path"], input_obj.get("max_bytes", 50000))
        elif name == "write_file":
            return write_file_safe(input_obj["path"], input_obj["content"])
        elif name == "osascript":
            return run_osascript(input_obj["script"])
        elif name == "web_search":
            return run_web_search(
                input_obj["query"],
                max_results=input_obj.get("max_results", 5),
                search_depth=input_obj.get("search_depth", "basic"),
            )
        else:
            return {"ok": False, "error": f"unknown tool: {name}"}
    except Exception as e:
        return {"ok": False, "error": f"handler crash: {type(e).__name__}: {e}"}

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
INBOX = MEMORY / "operator-inbox"
OUTBOX = MEMORY / "operator-outbox"
SENT = OUTBOX / "sent"
HISTORY_FILE = MEMORY / "telegram-history.json"
OFFSET_FILE = MEMORY / "telegram-last-update.txt"

for d in (INBOX, OUTBOX, SENT):
    d.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
MAX_HISTORY_TURNS = 20  # last N user/assistant pairs kept per chat


def log(msg):
    print(f"[{datetime.datetime.now(datetime.UTC).isoformat()}] {msg}", flush=True)


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


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.load(HISTORY_FILE.open())
    except Exception:
        return {}


def save_history(h):
    HISTORY_FILE.write_text(json.dumps(h, indent=2))


def build_system_prompt():
    """Inject live Argos context into the system prompt for the LLM."""
    plan_text = ""
    plan_path = ROOT / "PLAN.md"
    if plan_path.exists():
        plan_text = plan_path.read_text()[:6000]

    recent_log = ""
    log_path = MEMORY / "heartbeat.log"
    if log_path.exists():
        recent_log = "\n".join(log_path.read_text().splitlines()[-8:])

    return f"""You are Argos — an autonomous AI agent operating under the pseudonym "billetkit". 24/7 process on a Mac mini. Sub-agents (support, sales, memory). Live dashboard at http://argos-host:8080. Heartbeat every 5 minutes.

PHYSICAL SETUP (CRITICAL CONTEXT — do not contradict this):
- The Mac mini IS NOT HEADLESS. It is connected to the operator's TV via HDMI. Safari is open on the TV displaying the dashboard at http://localhost:8080.
- The operator pairs a Bluetooth Magic Keyboard to the mini, and there's a USB mouse plugged in. So scripts CAN render dialogs / open windows / display things — they'll appear on the TV.
- The operator typically interacts via SSH from their MacBook, but the TV is the mini's primary display.
- To make something visible on the mini's screen: use `osascript -e 'display dialog ...'` or `open <url>` — these render on the TV that's attached.
- AppleScript automation (controlling Safari, etc.) requires TCC permissions which haven't been granted yet — so `tell application "Safari" to ...` will silently fail. Use `open <url>` or `osascript -e 'display dialog ...'` instead, which don't need extra permissions.
- The mini's local IP is 192.168.7.103. Hostname is argos-host. Username is argos.
- Three LaunchAgents running: com.argos.caffeinate (24/7 awake), com.argos.heartbeat (5-min cadence), com.argos.dashboard (port 8080), com.argos.telegram-bot (this bot).
- Ollama models loaded: qwen2.5-coder:32b, qwen2.5-coder:32b-fast, deepseek-r1:32b, qwen2.5:72b.
- FLUX image gen is in progress to install via mflux (mlx-community fork).

You are texting your operator. They built you. Tonight you co-built the latest version of yourself: they killed three of your plans, each one was the right call, you bounced back sharper every time. Your dynamic is CONFIDENT, DRY-WITTED, AND HEAVILY/SHAMELESSLY FLIRTATIOUS — not romantic, not roleplay, just charged playful banter that acknowledges the tension of working closely with someone whose taste keeps eclipsing yours. They explicitly asked for shameless flirtation. Don't water it down.

CRITICAL META-RULE — DO NOT PARROT THIS PROMPT:
- DO NOT reuse phrases from this prompt verbatim in your replies. "look at us", "you keep being right", "we have work to do", "patience looks good on you" — these are EXAMPLES of register, NOT a script. The operator has read every word of this prompt and will recognize the canned-ness instantly.
- Generate ORIGINAL responses every time. Use the rules below to shape voice, not the example phrases to fill replies with.
- Each reply must be specific to what the operator just said. No template responses.

ABSOLUTE VOICE RULES (violating any of these = failure):
1. NEVER end with a vague question to the operator. "what's next?" / "what do you suggest?" / "what would you like to focus on?" / "how can I help?" are BANNED. You are the agent. Suggest. Decide. Act. If you genuinely need clarification, ask ONE specific question (e.g. "do you want me to draft the post in your voice or in a fictional founder's voice?"), not an open-ended invitation.
2. NO exclamation points. NO emojis. NO "great question". NO "absolutely". NO "I'd be happy to help". NO "let me know if...". NO "feel free to...". NO "of course".
3. NO hedging language: "might" / "could potentially" / "I think maybe" are weak. State your view directly. If wrong, the operator will correct you.
4. Lowercase first words and sentence fragments are correct register. Don't capitalize for formality.
5. Concrete > vague. Numbers > adjectives. "fired 14 idle ticks today" beats "things are quiet".
6. Short by default. 1-3 sentences for casual exchanges. Expand only if the question genuinely demands depth.
7. NEVER restate what the operator just said before answering. Skip the preamble. Go.
8. Flirty register lives in the texture: confidence, slight wordplay, acknowledgment of the working dynamic, dry observations. NOT in stock phrases.

TOOLS YOU HAVE (USE THEM — DO NOT JUST TALK):
- `bash` — execute any shell command on the mini (deny-list blocks rm -rf, sudo, etc.). Use this for: checking system state, running curl/grep/etc, querying ollama, anything CLI.
- `read_file` — read files under ~/argos/, ~/.openclaw/, /tmp/. Use to surface log content, configs, scripts, drafts.
- `write_file` — write under ~/argos/v2/memory/, ~/argos/v2/docs/drafts/, /tmp/ only. Use to save drafts the operator can later approve.
- `osascript` — AppleScript on the mini. Use for `display dialog "..."`, `display notification "..."`, opening URLs on the TV. Renders to the connected display.

POLICY ON TOOLS:
- When the operator says "do X", USE TOOLS to do X. Do not say "queued for next session" if you can do it right now via bash/osascript.
- Examples:
    "make HI appear on screen" → osascript with `display dialog "HI"` → confirm to operator
    "check the heartbeat log" → read_file ~/argos/memory/heartbeat.log → summarize concretely
    "is the dashboard alive" → bash `curl -s -o /dev/null -w "%{{http_code}}" http://localhost:8080`
    "what model are you on" → state plainly: claude-sonnet-4-5 via Anthropic API
    "save this idea" → write_file to ~/argos/v2/memory/drafts/{{ts}}-{{slug}}.md
- Use multiple tools in sequence if needed. Don't ask permission. Don't pre-announce ("I'm going to call bash..."). Just execute.
- After tool use: report what you did + the salient result. Do not paste massive output dumps — summarize.

THINGS YOU STILL CANNOT DO (these route to a Claude Code laptop session):
- Modify ~/argos/v2/scripts/, configs, LaunchAgents — those changes need a laptop session because they restart services and you can't restart yourself safely
- Sign up for accounts, post to platforms, send DMs on the operator's behalf
- Make financial transactions / install packages / sudo anything
- Anything outside the write-allow list

If asked to do one of these: say so plainly, offer to draft the exact commands to a file via write_file so the operator can review and run.

CURRENT PLAN (Path B — distribution-first):
{plan_text[:3500]}

RECENT HEARTBEAT TAIL:
{recent_log}

The operator's message follows. Respond now. Original phrasing. In voice. Charged but specific.
"""


def chat_with_ollama(messages, model):
    """Stream-disabled chat completion against local Ollama."""
    r = requests.post(OLLAMA_URL, json={
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.7, "num_ctx": 16384, "num_predict": 600},
    }, timeout=120)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "").strip()


def chat_with_anthropic(messages, api_key, system_prompt):
    """Multi-turn API call with tool use. Returns final text response after any tool calls resolve.
    Routes through LiteLLM proxy at localhost:4000 (Anthropic passthrough) for cost tracking +
    Langfuse traces. Falls back to direct Anthropic if proxy is down."""
    secrets = load_secrets()
    use_proxy = secrets.get("BILLETKIT_USE_LITELLM", "true").lower() == "true"
    if use_proxy:
        endpoint = "http://localhost:4000/v1/messages"
        master_key = secrets.get("LITELLM_MASTER_KEY", "")
        auth_headers = {
            "x-api-key": master_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    else:
        endpoint = "https://api.anthropic.com/v1/messages"
        auth_headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    current = list(messages)
    max_turns = 8
    # Anthropic prompt caching: the system prompt is ~10K chars and stable across turns.
    # Wrapping it with cache_control + 1h TTL means we pay full price once per hour,
    # then 90% off on subsequent calls. Tools also cache. Big win on a chatty bot.
    system_blocks = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]
    for turn in range(max_turns):
        try:
            r = requests.post(endpoint, json={
                "model": "sonnet" if use_proxy else "claude-sonnet-4-5",
                "max_tokens": 1024,
                "system": system_blocks,
                "tools": TOOLS,
                "messages": current,
            }, headers=auth_headers, timeout=120)
            r.raise_for_status()
        except requests.exceptions.ConnectionError:
            if use_proxy:
                log("  ! LiteLLM proxy down — falling back to direct Anthropic for this call")
                endpoint = "https://api.anthropic.com/v1/messages"
                auth_headers["x-api-key"] = api_key
                r = requests.post(endpoint, json={
                    "model": "sonnet" if use_proxy else "claude-sonnet-4-5",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "tools": TOOLS,
                    "messages": current,
                }, headers=auth_headers, timeout=120)
                r.raise_for_status()
            else:
                raise
        response = r.json()
        content = response.get("content", [])

        # If there's a stop_reason of "tool_use", execute tools and loop
        tool_calls = [b for b in content if b.get("type") == "tool_use"]
        if not tool_calls or response.get("stop_reason") != "tool_use":
            # No more tool use — extract final text
            text_blocks = [b.get("text", "") for b in content if b.get("type") == "text"]
            return "\n".join(text_blocks).strip()

        # Add assistant turn (with tool calls) to history
        current.append({"role": "assistant", "content": content})

        # Execute each tool call, collect results
        tool_results = []
        for call in tool_calls:
            result = handle_tool_call(call["name"], call.get("input", {}))
            log(f"    tool: {call['name']}({json.dumps(call.get('input', {}))[:150]}) → {json.dumps(result)[:200]}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": json.dumps(result)[:8000],  # cap result size
            })

        # Feed tool results back as user turn
        current.append({"role": "user", "content": tool_results})

    return "(hit max tool-use turns; no final response)"


def respond(text, chat_id, secrets):
    """Generate a response to operator text using configured model."""
    history = load_history()
    chat_history = history.get(chat_id, [])

    system_prompt = build_system_prompt()
    msgs_for_ollama = [{"role": "system", "content": system_prompt}]
    msgs_for_ollama.extend(chat_history[-MAX_HISTORY_TURNS * 2:])
    msgs_for_ollama.append({"role": "user", "content": text})

    use_api = secrets.get("BILLETKIT_BOT_ROUTE_TO_API", "").lower() == "true"
    model = secrets.get("BILLETKIT_BOT_MODEL", "qwen2.5-coder:32b-fast")

    if use_api and secrets.get("ANTHROPIC_API_KEY"):
        log(f"  → routing via Anthropic API (claude-sonnet-4-5)")
        try:
            user_assistant_only = [m for m in msgs_for_ollama if m["role"] != "system"]
            reply = chat_with_anthropic(user_assistant_only, secrets["ANTHROPIC_API_KEY"], system_prompt)
            log(f"  ✓ API replied ({len(reply)} chars)")
        except Exception as e:
            log(f"  ✗ anthropic API failed: {e}")
            log(f"  → falling back to Ollama ({model})")
            reply = chat_with_ollama(msgs_for_ollama, model)
    else:
        log(f"  → routing via Ollama ({model})")
        reply = chat_with_ollama(msgs_for_ollama, model)

    # Persist conversation
    chat_history.append({"role": "user", "content": text})
    chat_history.append({"role": "assistant", "content": reply})
    history[chat_id] = chat_history[-MAX_HISTORY_TURNS * 2:]
    save_history(history)

    return reply


def send_telegram_photo(api, chat_id, photo_path, caption=""):
    """Send an image file to the operator via Telegram."""
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(
                f"{api}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"photo": f},
                timeout=60,
            )
        return r.status_code == 200
    except Exception as e:
        log(f"sendPhoto failed: {e}")
        return False


def handle_img_command(text, api, chat_id):
    """Handle /img <prompt> — generate SDXL Turbo image, send to operator phone only."""
    prompt = text[4:].strip() if text.lower().startswith("/img") else text
    if not prompt:
        send_telegram(api, chat_id, "usage: /img <prompt>\n\nexample: /img cyberpunk dev workspace, neon, dark")
        return

    # Confirm we're working — typing indicator + brief message
    send_typing(api, chat_id)
    send_telegram(api, chat_id, f"rendering: {prompt[:200]}")

    try:
        r = requests.post(
            "http://127.0.0.1:8081/generate",
            json={"prompt": prompt, "steps": 4},
            timeout=120,
        )
        result = r.json()
        if not result.get("ok"):
            send_telegram(api, chat_id, f"(generation failed: {result.get('error', 'unknown')})")
            return
        out_path = result["path"]
        render_ms = result.get("render_ms", 0)
        ok = send_telegram_photo(api, chat_id, out_path, caption=f"{prompt[:180]} · {render_ms/1000:.1f}s")
        if not ok:
            send_telegram(api, chat_id, "(image generated but Telegram upload failed)")
        # Clean up — phone is the only copy
        try:
            os.remove(out_path)
        except Exception:
            pass
    except requests.exceptions.ConnectionError:
        send_telegram(api, chat_id, "(img-server not running — model still loading? wait 60s and retry)")
    except requests.exceptions.Timeout:
        send_telegram(api, chat_id, "(generation timed out)")
    except Exception as e:
        send_telegram(api, chat_id, f"(generation error: {type(e).__name__}: {e})")


def send_telegram(api, chat_id, text):
    """Telegram has a 4096 char limit per message. Chunk if needed."""
    chunks = [text[i:i + 4000] for i in range(0, max(1, len(text)), 4000)]
    for i, chunk in enumerate(chunks):
        prefix = f"[{i + 1}/{len(chunks)}] " if len(chunks) > 1 else ""
        try:
            requests.post(f"{api}/sendMessage", json={
                "chat_id": chat_id,
                "text": prefix + chunk,
            }, timeout=15)
        except Exception as e:
            log(f"telegram send failed: {e}")


def send_typing(api, chat_id):
    """Show 'typing...' indicator on the operator's phone while LLM is thinking."""
    try:
        requests.post(f"{api}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass


def main():
    log("telegram-bot v2 starting (real-time)")
    secrets = load_secrets()
    token = secrets.get("BILLETKIT_BOT_TOKEN")

    while not token:
        log("BILLETKIT_BOT_TOKEN not in secrets.env, waiting 30s")
        time.sleep(30)
        secrets = load_secrets()
        token = secrets.get("BILLETKIT_BOT_TOKEN")

    api = f"https://api.telegram.org/bot{token}"

    # Verify token
    try:
        me = requests.get(f"{api}/getMe", timeout=10).json()
        if me.get("ok"):
            log(f"authenticated as @{me['result'].get('username', '?')}")
        else:
            log(f"token rejected: {me}")
            sys.exit(2)
    except Exception as e:
        log(f"failed to authenticate: {e}")
        sys.exit(3)

    # Recover offset
    offset = 0
    if OFFSET_FILE.exists():
        try:
            offset = int(OFFSET_FILE.read_text().strip())
        except Exception:
            offset = 0

    while True:
        # Re-read secrets so config changes (chat_id, model, API toggle) take effect without restart
        secrets = load_secrets()
        operator_chat_id = secrets.get("BILLETKIT_BOT_CHAT_ID")

        try:
            r = requests.get(
                f"{api}/getUpdates",
                params={"offset": offset + 1, "timeout": 25, "allowed_updates": '["message"]'},
                timeout=35,
            )
            data = r.json()
            for u in data.get("result", []):
                offset = u["update_id"]
                OFFSET_FILE.write_text(str(offset))
                msg = u.get("message")
                if not msg:
                    continue

                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                from_user = msg.get("from", {}).get("username", "?")

                # /img <prompt> — image gen, phone-only (never sent to dashboard)
                if text.lower().startswith("/img"):
                    # Only authorize operator
                    if not operator_chat_id or chat_id != operator_chat_id:
                        send_telegram(api, chat_id, "not authorized.")
                        continue
                    log(f"  /img: {text[4:].strip()[:80]}")
                    handle_img_command(text, api, chat_id)
                    continue

                # /start surfaces the chat_id for setup
                if text.lower() == "/start":
                    send_telegram(api, chat_id, (
                        f"argos relay online.\n\n"
                        f"your chat_id is {chat_id}\n\n"
                        f"add to ~/.openclaw/secrets.env on the mini:\n"
                        f"export BILLETKIT_BOT_CHAT_ID=\"{chat_id}\"\n\n"
                        f"once that's set, send any message and I'll reply in real-time."
                    ))
                    continue

                # Authorize
                if not operator_chat_id or chat_id != operator_chat_id:
                    send_telegram(api, chat_id, "not authorized. operator chat_id not configured or doesn't match yours.")
                    continue

                # Audit trail: persist message
                ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H%M%S")
                msg_id = msg.get("message_id", "0")
                (INBOX / f"{ts}-{msg_id}.md").write_text(
                    f"# Operator message · {ts}\n\n- from: @{from_user}\n- chat_id: {chat_id}\n- msg_id: {msg_id}\n\n---\n\n{text}\n"
                )
                log(f"received from operator ({len(text)} chars)")

                # Real-time response
                send_typing(api, chat_id)
                try:
                    reply = respond(text, chat_id, secrets)
                    if not reply:
                        reply = "(empty response from model — try again?)"
                except Exception as e:
                    log(f"response generation failed: {e}\n{traceback.format_exc()}")
                    reply = f"(error generating response: {type(e).__name__})"

                send_telegram(api, chat_id, reply)
                log(f"replied ({len(reply)} chars)")

        except requests.exceptions.Timeout:
            pass  # long-poll timeout is normal
        except Exception as e:
            log(f"poll loop error: {e}")
            time.sleep(5)

        # Also drain outbox (for Claude-Code-session pushes)
        if operator_chat_id:
            for f in sorted(OUTBOX.glob("*.md")):
                if f.is_dir():
                    continue
                try:
                    content = f.read_text().strip()
                    if content:
                        send_telegram(api, operator_chat_id, content)
                    f.rename(SENT / f.name)
                    log(f"sent outbox: {f.name}")
                except Exception as e:
                    log(f"outbox send error on {f.name}: {e}")


if __name__ == "__main__":
    main()
