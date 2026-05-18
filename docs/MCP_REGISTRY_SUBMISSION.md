# MCP Registry Submission — billetkit-voice-grader

The package is built and registry-submission-ready in `packages/billetkit-voice-grader/`. The actual publishing requires accounts you (not the bot) must create. Step-by-step, in priority order:

## 1. Official MCP Registry (`registry.modelcontextprotocol.io`) — highest leverage

This is what Claude Desktop, Cursor, Cline, etc. actually *query* when users search for MCPs. Submission is **GitHub-OAuth based** — uses your existing `billetkit` GitHub identity, no new accounts.

```bash
# (one-time) install the publisher CLI
pip install mcp-publisher

# Build + publish to PyPI (requires you to create a PyPI account first if you don't have one)
cd /Users/argos/argos/packages/billetkit-voice-grader
pip install build twine
python -m build
twine upload dist/*    # PyPI prompts for username + token

# Submit to Official Registry
mcp-publisher login github
# (opens browser to github.com/login/device, paste the code)
mcp-publisher publish
```

The `server.json` is already at `packages/billetkit-voice-grader/server.json` with the right `io.github.billetkit/...` name.

Time to submit: **~10 minutes** once you have the PyPI account.

## 2. Smithery (`smithery.ai`) — most-used third-party registry

7,000+ servers indexed. Standalone account.

```bash
# Install Smithery CLI
npm install -g @smithery/cli

# Login (web auth flow)
smithery login

# Publish — points at the PyPI package
smithery mcp publish io.github.billetkit/billetkit-voice-grader
```

Or via web at https://smithery.ai → "Add server" → paste GitHub URL.

Time: **~5 minutes** post-PyPI publish.

## 3. awesome-mcp (GitHub repo) — community-maintained list

Pure GitHub PR. No new account needed (uses your billetkit GitHub).

```bash
gh repo fork punkpeye/awesome-mcp-servers --clone
cd awesome-mcp-servers
# Add an entry under the appropriate section, e.g. "Content quality":
#   - [billetkit-voice-grader](https://github.com/billetkit/argos-stack/tree/main/packages/billetkit-voice-grader) — AI-slop detection + 2026 anti-tell voice grading. Drop in front of any LLM that produces customer-facing prose.
git checkout -b add-billetkit-voice-grader
git commit -am "add billetkit-voice-grader"
gh pr create --fill
```

Time: **~5 minutes**.

## 4. mcp.so — community aggregator

Auto-indexes from GitHub if your repo has the right tags. Just make sure `package.json` (or `pyproject.toml`) has the right keywords:
- `mcp`
- `model-context-protocol`
- `mcp-server`

Already in place in our `pyproject.toml`. Should auto-index within 48h.

## 5. Optional smaller directories (one PR each, copy-paste from #3)

Per the DEV.to writeup "5 things I learned submitting to 27 MCP directories" — diminishing returns but cheap to add:
- https://github.com/wong2/awesome-mcp-servers
- https://github.com/appcypher/awesome-mcp-servers
- https://mcpserverfinder.com (form submission)
- https://glama.ai/mcp (form submission)

Skip directories that haven't been updated in 60+ days.

## Distribution payoff math

Per the Postiz precedent (research dive 7), $20K → $88K MRR in 60 days came from a **single registry submission** doing the discovery work. The "sell to AI agents" market is well-formed by mid-2026; every Cursor/Claude Desktop user searching "ai detector" or "voice grader" in their MCP installer is a potential install.

Conservative estimate at 6 months post-registry-submission:
- ~500-2,000 installs across all registries
- ~10-30% activation (set up API key, run once)
- ~5% paid conversion if we add a hosted tier later
- Hosted tier pricing: $19/mo at the indie SaaS sweet spot

That's $500-2K MRR potential from the voice-grader alone. The same pattern scales — billetkit can publish the slop checker as its own server, the Bluesky helper as another, the Reddit warmer logic as a third. Each registry submission compounds.

## Caveat

This package depends on an LLM backend (Anthropic API or Ollama). Users without an API key get a useful error. Document this prominently or some installs will churn at "first run failed."
