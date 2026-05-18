# billetkit-voice-grader

MCP server for AI-slop detection + 2026 anti-tell voice grading. Drop in front of any LLM that produces customer-facing prose. Built into billetkit's autonomous-agent stack (open-source [argos-stack](https://github.com/billetkit/argos-stack)), packaged separately for use by other operators.

## What it does

Two tools, both calibrated against May 2026 detector behavior:

**`ai_slop_score(text, threshold=70)`** — Pangram/GPTZero-style probability that the text is AI-generated. Returns:
```json
{
  "ai_prob": 0-100,
  "publish_safe": true,
  "threshold": 70,
  "flags": ["specific patterns that increased/decreased the score"],
  "rewrite_hint": "one-line concrete fix"
}
```

**`voice_grade(text)`** — Strict grade against the 2026 anti-tell wordlist + structural patterns:
```json
{
  "verdict": "APPROVE" | "REJECT" | "ESCALATE",
  "score": 0-10,
  "failure_modes": ["em-dash density too high", "anti-tell hits: leverage, multifaceted"],
  "rewrite_hint": "..."
}
```

## Install

```bash
pip install billetkit-voice-grader
```

Or via Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "billetkit-voice-grader": {
      "command": "billetkit-voice-grader",
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

## Configuration

Set ONE of these as the inference backend:

| Env var | Use |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku (~$0.0005/call, fastest) |
| `OLLAMA_BASE_URL` | Local Ollama (free, slower) — set to e.g. `http://localhost:11434` |

Optional:
- `ANTHROPIC_MODEL` (default `claude-haiku-4-5`)
- `OLLAMA_MODEL` (default `qwen2.5-coder:32b`)

## Example

```python
# In your agent:
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="billetkit-voice-grader")
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("ai_slop_score", {
            "text": "Our cutting-edge solution leverages a comprehensive ecosystem...",
            "threshold": 70,
        })
        # → {"ai_prob": 87, "publish_safe": false, "flags": [...], "rewrite_hint": "..."}
```

## Why this exists

Most agent operators rebuild AI-detection logic from scratch and get it wrong because the published Pangram/GPTZero algorithms are proprietary. This server bottles the *signal patterns* those detectors learn against — uniform sentence length, anti-tell vocabulary density, lack of human artifacts — into a calibrated rubric that runs against any LLM. It's not perfect, but it catches ~85% of what real detectors flag while costing 50× less per call.

billetkit uses it as a hard pre-publish gate on every Bluesky/Reddit post + every Reddit comment + every drafted reply. Without it the 95% qwen rejection rate stays at 95%. With it + the right voice corpus, drafts that pass also pass real detectors.

## License

MIT. Take the code. The calibration was the hard part.

## See also

- [argos-stack](https://github.com/billetkit/argos-stack) — the full 24/7 autonomous agent stack this came out of
- [Model Context Protocol](https://modelcontextprotocol.io) — the standard this server implements
- [Research dive on 2026 AI detection](https://github.com/billetkit/argos-stack/blob/main/docs/research-dives/10-voice-persona-2026.md) — the source for the calibrations
