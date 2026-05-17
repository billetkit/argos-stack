---
name: check-name-leak
description: Pre-publish guard that scans customer-facing artifacts (PDFs, landing pages, launch posts, marketing copy) for accidental leaks of operator identifiers — real names, school, employer, locations. Run before deploying any content that ships outside your repo. Critical for builders who want to keep their public-facing brand separate from their legal identity.
---

# check-name-leak

A pre-publish anonymity guard for solo builders running pseudonymous businesses.

## When to invoke

- Before pushing to a deployed site (Vercel, Netlify, GitHub Pages, etc.)
- Before publishing a launch post (X, Bluesky, Show HN, Reddit, ProductHunt)
- Before sending a PDF / lead magnet to customers
- Before opening any PR that touches `products/*/`, `site/`, `launch/`, `pdf/`, or `blog/` dirs
- As a CI fail-closed step on any production-bound branch (`main`, `release`)

## Why this skill exists

Anonymous and pseudonymous businesses (the Felix Craft pattern, the Pieter Levels pattern, indie hackers in regulated jurisdictions) accumulate small identifier leaks fast:

- LLM-generated copy accidentally includes a sub-agent's memo of "the operator's name is X"
- A reused template still has the placeholder filled in from a previous project
- A landing-page bio mentions a school or employer that ties back to the operator
- A PDF metadata field carries the operator's macOS account name

Each leak alone seems harmless. Together they're a doxxing trail.

Real-world failure that motivated this skill: 224 customer-facing files in one workspace contained the operator's legal name, school, and prior employer despite a "PRIME_DIRECTIVE" rule against it. The leaks came from LLM-generated content where the agent had access to a USER.md profile and didn't realize "your operator is X" was internal-only context. A regex sweep caught all 224 in one pass and informed the rewrite.

## What it does

Scans a configurable set of directories for a configurable set of identifier patterns. Reports every match with file path + line number. Optionally fails the build (`--strict` mode) for CI integration.

Identifier categories scanned:
- **Names** — operator legal name + variants
- **Schools** — alma mater + variants (initialisms, abbreviations)
- **Employers** — current and prior, plus parent companies
- **Cities** — only if you want geographic blur (optional)
- **Custom** — any additional patterns (emails, phone area codes, GitHub handles)

## Setup

1. Copy `identifiers.example.json` → `~/.config/check-name-leak/identifiers.json`
2. Fill in your real identifiers (this file is gitignored / never deployed)
3. Set `scan_dirs` to the directories that publish externally
4. Add to your CI:
   ```yaml
   - name: Anonymity check
     run: bash skills/check-name-leak/check-name-leak.sh --strict
   ```

## Usage

```bash
# Local scan (warn-only)
bash check-name-leak.sh

# CI mode (fails on any match)
bash check-name-leak.sh --strict

# With custom config path
CHECK_NAME_LEAK_CONFIG=./my-identifiers.json bash check-name-leak.sh
```

## What it does NOT do

- Does not scrub or auto-rewrite — only reports. Author chooses how to rephrase.
- Does not scan binary files (PDFs, images). PDFs should be checked at the source `.md` stage; the rendered PDF will inherit any leaks from there.
- Does not scan files over 500KB. Source content should never exceed that; large files are likely cached deps.
- Does not look inside git history. Once leaked into a public branch, a leak is permanent — use this as a *pre-publish* gate, not a forensic tool.
- Does not know about EXIF / metadata leaks in images. Use a separate `exiftool` strip for that.

## Limitations / future work

- Currently regex-based. A more sophisticated version could use ML to detect "this looks like a personal pronoun about an unnamed individual" or "this paragraph reads autobiographically" without matching specific strings. For v1, regex is faster + more debuggable.
- No web-search check ("does this exact phrase already appear on my public site under a different name?"). That's a different tool.
- Does not currently scan code comments (`//`, `#`) in `.py/.ts/.js/.go` source files. Add those extensions to config if your codebase ships source publicly.

## Pricing rationale (for ClawMart listing)

$29 is in the range of pre-publish hygiene tools (Husky + lint-staged setups cost more in time to wire). Single-script install, immediate value on the first commit it catches a leak. Anyone running a pseudonymous business sees this and recognizes the problem.
