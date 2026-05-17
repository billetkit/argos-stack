#!/usr/bin/env python3
"""voice-samples.py — Build a real voice corpus from the operator's writing.

The dream of 2026-05-17 proposed: 'every time the operator writes something
in their voice (texts, emails, approved edits, github commits), append it to a
voice_samples.txt that the sales sub-agent loads as few-shot context. The voice
isn't in the style guide, it's in the data.'

This script collects samples from:
  - operator-inbox/ (Telegram messages from operator)
  - drafts/approved/ (drafts that passed the voice grader)
  - git log on billetkit/argos-stack (operator's commit messages)

Filters: 30-400 chars per sample (substantive, not one-word).
Output: ~/argos/memory/voice-samples.txt (last 200, FIFO).

Fires nightly at 03:45, before morning digest, after dream.
Sub-agents that need voice anchoring read this file at load time.
"""
import os, json, pathlib, datetime, re, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMORY = ROOT / "memory"
OUTPUT = MEMORY / "voice-samples.txt"

MAX_SAMPLES = 200
MIN_CHARS = 30
MAX_CHARS = 400


def collect_inbox_samples():
    """Operator's phone messages — their texting voice unfiltered."""
    inbox = MEMORY / "operator-inbox"
    archive = inbox / "archive"
    samples = []
    for d in [inbox, archive]:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                text = f.read_text()
                # body is after "---\n\n" per our schema
                if "---" not in text:
                    continue
                body = text.split("---", 1)[1].strip()
                # strip the trailing newline + meta
                body = re.sub(r"\n+$", "", body)
                if MIN_CHARS <= len(body) <= MAX_CHARS:
                    samples.append({"source": "telegram", "text": body, "mtime": f.stat().st_mtime})
            except Exception:
                pass
    return samples


def collect_approved_drafts():
    """Drafts that passed the auto-grader — they sound enough like the operator to ship."""
    approved = MEMORY / "drafts" / "approved"
    samples = []
    if not approved.exists():
        return samples
    for f in approved.glob("*.md"):
        try:
            text = f.read_text()
            # Strip metadata header and auto-grader note
            text = re.sub(r"^#.*?---\n\n", "", text, flags=re.DOTALL)
            text = re.sub(r"\n---\n_Auto-graded.*", "", text, flags=re.DOTALL)
            text = text.strip()
            if MIN_CHARS <= len(text) <= MAX_CHARS * 3:
                # Split into individual paragraphs (more useful as few-shot units)
                for para in re.split(r"\n\s*\n", text):
                    para = para.strip()
                    if MIN_CHARS <= len(para) <= MAX_CHARS:
                        samples.append({"source": "approved-draft", "text": para, "mtime": f.stat().st_mtime})
        except Exception:
            pass
    return samples


def collect_git_commits():
    """Commit messages on argos-stack — operator's terse explanation voice."""
    samples = []
    repo = pathlib.Path("/tmp/argos-stack")
    if not repo.exists():
        return samples
    try:
        log = subprocess.check_output(
            ["git", "log", "--since=30 days ago", "--pretty=format:%H|||%s|||%b", "--no-merges"],
            cwd=str(repo), text=True, timeout=30,
        )
        for entry in log.split("\n"):
            if "|||" not in entry:
                continue
            parts = entry.split("|||", 2)
            if len(parts) < 2:
                continue
            subject = parts[1].strip()
            body = parts[2].strip() if len(parts) > 2 else ""
            full = f"{subject}\n\n{body}".strip() if body else subject
            if MIN_CHARS <= len(full) <= MAX_CHARS:
                samples.append({"source": "git-commit", "text": full, "mtime": 0})
    except Exception:
        pass
    return samples


def main():
    print(f"[voice-samples] starting at {datetime.datetime.now()}", flush=True)

    all_samples = []
    all_samples.extend(collect_inbox_samples())
    all_samples.extend(collect_approved_drafts())
    all_samples.extend(collect_git_commits())
    print(f"[voice-samples] collected {len(all_samples)} candidate samples", flush=True)

    # Dedup by exact text
    seen = set()
    deduped = []
    for s in sorted(all_samples, key=lambda x: -x["mtime"]):  # newest first
        if s["text"] in seen:
            continue
        seen.add(s["text"])
        deduped.append(s)

    # Cap at MAX_SAMPLES (newest first)
    deduped = deduped[:MAX_SAMPLES]
    print(f"[voice-samples] {len(deduped)} after dedup + cap", flush=True)

    if not deduped:
        print("[voice-samples] no samples to write, leaving prior file intact", flush=True)
        return

    # Write as plain text with a source-tag header per sample
    lines = [
        f"# voice samples — the operator's actual writing, not style rules",
        f"# generated {datetime.datetime.now().isoformat()}",
        f"# {len(deduped)} samples, sources: telegram + approved-drafts + git-commits",
        "",
    ]
    for s in deduped:
        lines.append(f"--- [{s['source']}] ---")
        lines.append(s["text"])
        lines.append("")

    OUTPUT.write_text("\n".join(lines))
    print(f"[voice-samples] wrote {OUTPUT} ({len(lines)} lines, ~{OUTPUT.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    main()
