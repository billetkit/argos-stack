# MCP Router — billetkit's tool aggregation layer

`lib/mcp_router.py` boots N stdio MCP servers as persistent subprocesses, aggregates their tools into a single namespace, and exposes a synchronous `call_tool()` API that existing `requests`-based callers (telegram-bot, heartbeat) can use without an async refactor.

## What's wired (May 2026)

The canonical 6-server billetkit set returned by `default_billetkit_servers(secrets)`:

| Key | Package | Tools | Surface |
|---|---|---:|---|
| `fs` | `@modelcontextprotocol/server-filesystem` | 14 | Sandboxed file I/O under `/Users/argos/argos` |
| `fetch` | `mcp-server-fetch` (uvx) | 1 | HTTP GET with markdown extraction |
| `memory` | `@modelcontextprotocol/server-memory` | 9 | Persistent knowledge graph (entities/relations/observations) |
| `git` | `mcp-server-git` (uvx) | 12 | Git ops on `/tmp/argos-stack` (the public repo clone) |
| `apple` | `apple-mcp` | 7 | Contacts, Notes, Messages, Mail, Reminders, Calendar, Maps via EventKit |
| `langfuse` | `mcp-langfuse` | 14 | Self-hosted Langfuse trace/dataset analysis |

**Total: 57 tools** Anthropic-compatible, namespaced as `<serverkey>__<toolname>`.

## Quick start

```python
from lib.mcp_router import MCPRouter, default_billetkit_servers

# secrets dict from parse_secrets()
router = MCPRouter(default_billetkit_servers(secrets))
router.wait_until_ready(timeout=90)

# 1) Build Anthropic tool schema (drop into the `tools` field of a Messages API call)
mcp_tools = router.as_anthropic_tools()  # list[dict]

# 2) When Claude returns tool_use blocks, dispatch:
for block in response.content:
    if block.type == "tool_use" and "__" in block.name:
        result = router.call_tool(block.name, block.input or {})
        # result = {"ok": bool, "content": str, "raw": ...}

# 3) On shutdown
router.close()
```

## Wiring into telegram-bot.py

1. **Boot router at process start** (single instance, daemon thread keeps servers alive):

```python
# At top of telegram-bot.py, after parse_secrets():
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lib"))
from mcp_router import MCPRouter, default_billetkit_servers

MCP_ROUTER = None
try:
    MCP_ROUTER = MCPRouter(default_billetkit_servers(secrets))
    MCP_ROUTER.wait_until_ready(timeout=90)
    log(f"mcp router booted: {sum(len(t) for t in MCP_ROUTER.tool_inventory().values())} tools")
except Exception as e:
    log(f"mcp router boot failed (continuing without): {e}")
```

2. **Merge MCP tools into TOOLS**:

```python
# Before each Anthropic API call:
all_tools = TOOLS + (MCP_ROUTER.as_anthropic_tools() if MCP_ROUTER else [])
# ...
r = requests.post(endpoint, json={
    "model": model,
    "tools": all_tools,
    # ...
})
```

3. **Dispatch MCP tool_use in the tool-handling loop**:

```python
def execute_tool(name, args):
    # existing handlers for bash/read_file/etc
    if name == "bash": return run_bash(args)
    if name == "read_file": return read_file_tool(args)
    # ... etc ...

    # MCP fallback — namespaced tools always contain "__"
    if MCP_ROUTER and "__" in name:
        r = MCP_ROUTER.call_tool(name, args)
        return {
            "type": "tool_result",
            "content": r["content"],
            "is_error": not r["ok"],
        }

    return {"type": "tool_result", "content": f"unknown tool: {name}", "is_error": True}
```

4. **Optional: clean shutdown on SIGTERM**:

```python
import signal
def _shutdown(sig, frame):
    if MCP_ROUTER: MCP_ROUTER.close()
    sys.exit(0)
signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)
```

## Operational notes

- **Boot is ~5-15s** total (npx fetches some packages on first run, then cached)
- **Stderr from MCP servers leaks** to the parent process by default; route through `subprocess.PIPE` if it gets noisy
- **fs is sandboxed** to `/Users/argos/argos`; trying to read `/etc/passwd` returns "Access denied - path outside allowed directories"
- **git points at `/tmp/argos-stack`** — the auto-changelog repo. Override via `BILLETKIT_GIT_REPO` in secrets if you want a different repo
- **apple-mcp needs Contacts/Calendar/etc. permissions** granted to whatever Python binary runs telegram-bot. Already granted as part of the May 2026 TCC blanket-grant session
- **Tool name collisions are avoided** by the `serverkey__toolname` namespace. Anthropic's tool name regex allows `_` so `__` is a safe separator
- **Router survives tool errors** — bad args, unknown tool, sandbox violations all return `{ok: False, content: <error>}` without crashing the loop

## Adding more servers (Stripe, Tavily, etc.)

When you get credentials, add to `default_billetkit_servers()` in `lib/mcp_router.py`:

```python
# Stripe (use a RESTRICTED read-only key)
if secrets.get("STRIPE_RESTRICTED_KEY"):
    servers["stripe"] = StdioServerParameters(
        command="npx",
        args=["-y", "@stripe/mcp", "--tools=customers.read,charges.read,payment_links.read,subscriptions.read",
              f"--api-key={secrets['STRIPE_RESTRICTED_KEY']}"],
    )

# Tavily (web search)
if secrets.get("TAVILY_API_KEY"):
    servers["tavily"] = StdioServerParameters(
        command="npx",
        args=["-y", "tavily-mcp"],
        env={"TAVILY_API_KEY": secrets["TAVILY_API_KEY"]},
    )
```

## Test commands

```bash
# Boot all servers, list tools, run a sample fs call
python3 lib/mcp_router.py

# Stress test (error handling + sequential calls)
python3 /tmp/mcp-router-stress.py
```
