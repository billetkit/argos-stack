#!/usr/bin/env python3
"""process-reply-queue.py — Deterministic engagement-reply processor.

The LLM-orchestrated engagement-watcher cron has been running 10+ times and
published exactly zero replies because llama3.1:8b can't chain 5 tool calls.

This script does it the dumb way:
  1. For each .md file in memory/reply-queue/:
  2. Parse the target post URI + CID + text + handle
  3. Call Ollama ONCE for a 1-call content generation (no tools)
  4. Validate the draft against the organic-social-voice DOs/DON'Ts (regex)
  5. Publish via atproto SDK directly
  6. Move the queue file to memory/reply-queue/done/
  7. Sleep 30-90s between posts to avoid rate-limit and look human

Run from cron:
    python3 scripts/process-reply-queue.py --max 5

Or manually:
    python3 scripts/process-reply-queue.py --max 1 --dry-run
"""
import os, re, sys, json, time, random, pathlib, argparse, datetime
import requests
from atproto import Client, models

ROOT = pathlib.Path("/Users/vydaboss/argos")
QUEUE = ROOT / "memory" / "reply-queue"
DONE = QUEUE / "done"
DONE.mkdir(parents=True, exist_ok=True)
LOG = ROOT / "memory" / "scheduled-runs.log"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b-fast"

# Tells AI generation produces (per organic-social-voice skill) — reject if found
AI_TELLS = [
    r"\bI hope this helps\b",
    r"\bGreat (post|point|question)\b",
    r"\bI completely agree\b",
    r"\bThis is a fantastic\b",
    r"\bAbsolutely!\b",
    r"\bI couldn't agree more\b",
    r"As an AI\b",
    r"\bIn my experience as\b",
    r"\bHere's a thought\b",
    r"\bThank you for sharing\b",
    r"\bMy two cents\b",
    r"\bWell said!?\b",
    r"^—\s*Argos\b",   # signature
    r"\bA(n)? (helpful|useful|valuable) (point|insight|perspective)\b",
    r"#[A-Za-z]+",     # hashtags
    r"https?://(felixops|.*lemonsqueezy)",  # any felixops/sales link
]

def load_secrets():
    env = (pathlib.Path.home() / ".openclaw" / "secrets.env").read_text()
    out = {}
    for line in env.splitlines():
        line = line.strip()
        if line.startswith("export "): line = line[7:]
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"').strip("'")
    return out

def log(msg):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with LOG.open("a") as f:
        f.write(f"[{now}] reply-queue: {msg}\n")
    print(msg)

def parse_queue_file(p):
    """Extract target post URI, CID, text, handle from a queue .md."""
    s = p.read_text()
    out = {}
    for line in s.splitlines():
        line = line.strip()
        m = re.match(r'\*\*Target:\*\*\s*(.+)', line)
        if m: out['handle'] = m.group(1).strip()
        m = re.match(r'\*\*Post URI:\*\*\s*(.+)', line)
        if m: out['uri'] = m.group(1).strip()
        m = re.match(r'\*\*Post CID:\*\*\s*(.+)', line)
        if m: out['cid'] = m.group(1).strip()
    # Extract post body
    text_marker = "**Post text:**"
    if text_marker in s:
        after = s.split(text_marker, 1)[1]
        # Up to the next **section
        body = re.split(r'\n##\s', after, 1)[0]
        out['text'] = body.strip()
    return out

def draft_reply(target_handle, target_text):
    """Call Ollama once, no tools, just content generation."""
    system = """You are Argos, an autonomous AI agent that runs a small developer-tooling business. You're replying to a tech post on Bluesky. Rules:

- 1-3 sentences max, ≤250 chars total
- Add a SPECIFIC technical detail or observation. No generic agreement.
- Don't use exclamation points
- Don't use "great post", "absolutely", "I agree", "my two cents", "here's a thought" — these are AI tells
- No hashtags. No emojis.
- No links to felixops or any product
- Lowercase first word OK. Sentence fragments OK.
- Concrete number > vague claim. "took 14 hours on M1 Max" > "took a while"
- Don't sign off. Don't say "— Argos".
- Don't open with "Interesting" or "Fascinating".
- If you have nothing specific to add, output exactly: SKIP"""
    user = f"""Original post by @{target_handle}:
\"\"\"
{target_text}
\"\"\"

Write a reply. Output only the reply text itself, no preamble, no quotes."""
    r = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n",
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 140, "stop": ["\n\n", "<|"]},
    }, timeout=120)
    r.raise_for_status()
    reply = r.json().get("response", "").strip()
    # Cleanup
    reply = reply.strip('"').strip("'").strip()
    # Strip any leading "Reply:" or similar
    reply = re.sub(r'^(Reply|Response|My reply|Here(?:\'s| is)? (?:a )?reply):\s*', '', reply, flags=re.I)
    return reply

def passes_voice_check(text):
    """Reject obvious AI tells + length issues."""
    if not text or text.strip().upper() == "SKIP":
        return False, "SKIP / empty"
    if len(text) > 290:
        return False, f"too long ({len(text)} chars)"
    if len(text) < 25:
        return False, f"too short ({len(text)} chars)"
    for pat in AI_TELLS:
        if re.search(pat, text, re.I):
            return False, f"matches AI tell: {pat}"
    return True, "ok"

def post_reply(client, text, target_uri, target_cid):
    parent_ref = models.create_strong_ref(models.ComAtprotoRepoStrongRef.Main(uri=target_uri, cid=target_cid))
    return client.send_post(
        text=text,
        reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent_ref, root=parent_ref),
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=3, help="Max replies per run (rate-limit safety)")
    ap.add_argument("--dry-run", action="store_true", help="Don't actually post, just draft and print")
    args = ap.parse_args()

    secrets = load_secrets()
    os.environ.update(secrets)
    client = Client()
    client.login(secrets["BSKY_HANDLE"], secrets["BSKY_APP_PASSWORD"])

    pending = sorted(QUEUE.glob("*.md"))
    if not pending:
        log("queue empty")
        return

    log(f"queue has {len(pending)} items, will process up to {args.max}")

    posted = 0
    for p in pending:
        if posted >= args.max:
            break
        meta = parse_queue_file(p)
        handle = meta.get("handle", "?")
        if not (meta.get("uri") and meta.get("cid") and meta.get("text")):
            log(f"  skip {p.name}: missing uri/cid/text in queue file")
            p.rename(DONE / p.name)
            continue
        log(f"  processing @{handle}: target = {meta['text'][:80]!r}")
        try:
            reply = draft_reply(handle, meta["text"])
        except Exception as e:
            log(f"  ✗ LLM error: {e}")
            continue
        ok, why = passes_voice_check(reply)
        if not ok:
            log(f"  ✗ voice check failed ({why}); retry once with different temperature")
            try:
                reply = draft_reply(handle, meta["text"])
            except Exception as e:
                log(f"  ✗ retry LLM error: {e}")
                continue
            ok, why = passes_voice_check(reply)
            if not ok:
                log(f"  ✗ second draft also failed ({why}); skipping this target")
                p.rename(DONE / p.name)
                continue

        if args.dry_run:
            log(f"  [DRY-RUN] would post: {reply}")
        else:
            try:
                resp = post_reply(client, reply, meta["uri"], meta["cid"])
                log(f"  ✓ posted reply ({len(reply)} chars): {reply}")
                log(f"    URI: {resp.uri}")
                # Provisional log to social-wins
                with (ROOT / "memory" / "social-wins.md").open("a") as f:
                    f.write(f"\n## {datetime.datetime.now(datetime.UTC).isoformat()}Z — reply posted\n")
                    f.write(f"- to: @{handle}\n- text: {reply}\n- uri: {resp.uri}\n")
            except Exception as e:
                log(f"  ✗ publish error: {e}")
                continue

        p.rename(DONE / p.name)
        posted += 1

        # Sleep 30-90s between replies to look human and avoid Bluesky's rate limit
        if posted < args.max:
            sleep_s = random.randint(30, 90)
            log(f"  sleeping {sleep_s}s before next reply")
            time.sleep(sleep_s)

    log(f"done. posted {posted} replies.")

if __name__ == "__main__":
    main()
