"""mcp_router.py — Boot N MCP servers as stdio subprocesses and route tool calls.

Wraps the async mcp Python SDK in a synchronous facade so existing requests-based
callers (telegram-bot.py, heartbeat.py) can use MCP tools without an async refactor.

Pattern:
- An asyncio loop runs in a daemon thread (started in __init__)
- Each MCP server is launched as a persistent stdio subprocess inside that loop
- Tools are aggregated, namespaced with `<serverkey>__<toolname>` to dodge collisions
- call_tool(name, args) is sync — submits a coroutine to the loop and blocks on result

Anthropic tool schema is generated from each server's listed JSONSchema and is ready
to inject into the `tools` parameter of an Anthropic Messages API call. Tool-use
results returned by Claude can be routed back through call_tool().

Usage (sync):
    router = MCPRouter(SERVERS)  # spawns thread + boots servers
    router.wait_until_ready(timeout=60)
    anthropic_tools = router.as_anthropic_tools()  # list[dict]
    # ... include in Anthropic API call ...
    result = router.call_tool("fs__read_text_file", {"path": "/Users/argos/argos/AGENTS.md"})
    # ... when shutting down ...
    router.close()
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)


@dataclass
class _ServerHandle:
    key: str
    session: ClientSession
    tools: list[dict]  # raw mcp tool listings — name, description, inputSchema


class MCPRouter:
    """Synchronous facade over async MCP stdio clients running in a daemon thread."""

    def __init__(self, servers: dict[str, StdioServerParameters], boot_timeout: int = 60):
        self.server_params = servers
        self.boot_timeout = boot_timeout
        self._handles: dict[str, _ServerHandle] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._stack: Optional[AsyncExitStack] = None
        self._boot_error: Optional[BaseException] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._start_thread()

    # ---- public sync API ----

    def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        ok = self._ready_event.wait(timeout=timeout)
        if self._boot_error:
            raise self._boot_error
        return ok

    def server_keys(self) -> list[str]:
        return list(self._handles.keys())

    def tool_inventory(self) -> dict[str, list[str]]:
        """{ serverkey: [tool_names] } — useful for logging/debug."""
        return {k: [t["name"] for t in h.tools] for k, h in self._handles.items()}

    def as_anthropic_tools(self) -> list[dict]:
        """Convert MCP tool listings to Anthropic tool_use schema.

        Each tool is namespaced `<serverkey>__<toolname>` so callers can route
        back to the right session. Anthropic's tool name regex allows _ but not
        / or :, so __ is a safe separator.
        """
        out: list[dict] = []
        for key, h in self._handles.items():
            for t in h.tools:
                out.append({
                    "name": f"{key}__{t['name']}",
                    "description": (t.get("description") or "").strip()[:1024],
                    "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
                })
        return out

    def call_tool(self, namespaced_name: str, arguments: dict[str, Any], timeout: float = 60.0) -> dict:
        """Synchronously invoke a tool. Returns {ok: bool, content: str, raw: ...}."""
        if "__" not in namespaced_name:
            return {"ok": False, "content": f"tool name '{namespaced_name}' missing server prefix"}
        key, _, tool_name = namespaced_name.partition("__")
        h = self._handles.get(key)
        if h is None:
            return {"ok": False, "content": f"unknown MCP server: {key}"}

        async def _invoke():
            return await h.session.call_tool(tool_name, arguments=arguments or {})

        fut = asyncio.run_coroutine_threadsafe(_invoke(), self._loop)  # type: ignore[arg-type]
        try:
            result = fut.result(timeout=timeout)
        except Exception as e:
            return {"ok": False, "content": f"{type(e).__name__}: {e}"}

        # MCP result.content is a list of TextContent / ImageContent objects
        text_parts = []
        for c in (result.content or []):
            t = getattr(c, "text", None)
            if t:
                text_parts.append(t)
        combined = "\n".join(text_parts) if text_parts else "(no text content)"
        return {
            "ok": not getattr(result, "isError", False),
            "content": combined,
            "raw": result,
        }

    def close(self, timeout: float = 10.0):
        if self._loop and not self._loop.is_closed() and self._shutdown_event is not None:
            # Signal the inner loop to exit cleanly so AsyncExitStack tears down
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # ---- async internals ----

    def _start_thread(self):
        self._thread = threading.Thread(target=self._thread_main, name="mcp-router", daemon=True)
        self._thread.start()

    def _thread_main(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._boot_and_serve())
        except BaseException as e:
            self._boot_error = e
            self._ready_event.set()
            log.exception("mcp router thread crashed")

    async def _boot_and_serve(self):
        async with AsyncExitStack() as stack:
            self._stack = stack
            for key, params in self.server_params.items():
                try:
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await asyncio.wait_for(session.initialize(), timeout=self.boot_timeout)
                    tools_resp = await asyncio.wait_for(session.list_tools(), timeout=self.boot_timeout)
                    tools = []
                    for t in tools_resp.tools:
                        tools.append({
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                        })
                    self._handles[key] = _ServerHandle(key=key, session=session, tools=tools)
                    log.info(f"mcp server '{key}' booted: {len(tools)} tools")
                except Exception as e:
                    log.warning(f"mcp server '{key}' failed to boot: {type(e).__name__}: {e}")
            self._shutdown_event = asyncio.Event()
            self._ready_event.set()
            # Keep the loop alive until close() signals shutdown
            try:
                await self._shutdown_event.wait()
            except asyncio.CancelledError:
                pass


# ---------- canonical billetkit MCP server set ----------

def default_billetkit_servers(secrets: dict) -> dict[str, StdioServerParameters]:
    """Return the standard 6-server set, with langfuse only if creds present."""
    fs_root = secrets.get("BILLETKIT_FS_ROOT", "/Users/argos/argos")
    git_repo = secrets.get("BILLETKIT_GIT_REPO", "/tmp/argos-stack")

    servers: dict[str, StdioServerParameters] = {
        "fs": StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", fs_root],
        ),
        "fetch": StdioServerParameters(
            command="uvx",
            args=["mcp-server-fetch"],
        ),
        "memory": StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
        ),
        "git": StdioServerParameters(
            command="uvx",
            args=["mcp-server-git", "--repository", git_repo],
        ),
        "apple": StdioServerParameters(
            command="npx",
            args=["-y", "apple-mcp"],
        ),
    }

    lf_host = secrets.get("LANGFUSE_HOST")
    lf_pub = secrets.get("LANGFUSE_PUBLIC_KEY") or secrets.get("LANGFUSE_PUBKEY")
    lf_sec = secrets.get("LANGFUSE_SECRET_KEY") or secrets.get("LANGFUSE_SECRETKEY")
    if lf_host and lf_pub and lf_sec:
        servers["langfuse"] = StdioServerParameters(
            command="npx",
            args=["-y", "mcp-langfuse"],
            env={
                "LANGFUSE_HOST": lf_host,
                "LANGFUSE_BASEURL": lf_host,
                "LANGFUSE_PUBLIC_KEY": lf_pub,
                "LANGFUSE_SECRET_KEY": lf_sec,
            },
        )

    # Tavily — adds a single `tavily__tavily-search` tool with multi-result
    # web search + extracted markdown. Replaces the brittle web_search fallback.
    tavily_key = secrets.get("TAVILY_API_KEY")
    if tavily_key:
        servers["tavily"] = StdioServerParameters(
            command="npx",
            args=["-y", "tavily-mcp"],
            env={"TAVILY_API_KEY": tavily_key},
        )

    # Stripe — DISABLED by default. @stripe/mcp 0.3.3 has no --tools= whitelist
    # so giving it a `sk_*` key exposes 31 tools including create_refund,
    # cancel_subscription, and stripe_api_execute (arbitrary endpoint by name).
    # Wire only when a restricted `rk_*` read-only key is in secrets, OR when the
    # operator explicitly accepts the risk via BILLETKIT_STRIPE_MCP_ALLOW_LIVE=true.
    stripe_restricted = secrets.get("STRIPE_RESTRICTED_KEY") or secrets.get("ARGOS_STRIPE_RESTRICTED_KEY")
    stripe_test = secrets.get("ARGOS_STRIPE_TEST_SECRET")
    stripe_live = secrets.get("ARGOS_STRIPE_SECRET")
    allow_live = secrets.get("BILLETKIT_STRIPE_MCP_ALLOW_LIVE", "").lower() == "true"
    prefer_test = secrets.get("BILLETKIT_STRIPE_MCP_USE_TEST", "").lower() == "true"

    stripe_key = None
    if stripe_restricted:
        stripe_key = stripe_restricted   # safest — restricted key enforces scope at the API layer
    elif prefer_test and stripe_test:
        stripe_key = stripe_test          # test mode, can't touch real money
    elif allow_live and stripe_live:
        stripe_key = stripe_live          # operator explicitly accepted the risk

    if stripe_key:
        servers["stripe"] = StdioServerParameters(
            command="npx",
            args=["-y", "@stripe/mcp", f"--api-key={stripe_key}"],
        )

    return servers


# ---------- smoke test ----------

if __name__ == "__main__":
    import json
    import pathlib

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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

    secrets = load_secrets()
    servers = default_billetkit_servers(secrets)
    print(f"booting {len(servers)} MCP servers: {list(servers.keys())}")

    router = MCPRouter(servers)
    router.wait_until_ready(timeout=90)

    print("\n=== server inventory ===")
    inv = router.tool_inventory()
    for k, tools in inv.items():
        print(f"  {k}: {len(tools)} tools")
    total = sum(len(t) for t in inv.values())
    print(f"total: {total} tools across {len(inv)} servers")

    anthropic_tools = router.as_anthropic_tools()
    print(f"\nanthropic_tools schema count: {len(anthropic_tools)}")
    print("first 3 tool names:", [t["name"] for t in anthropic_tools[:3]])

    # Sample real invocation: read AGENTS.md via fs server
    print("\n=== sample tool call: fs__read_text_file on AGENTS.md ===")
    r = router.call_tool("fs__read_text_file", {"path": "/Users/argos/argos/AGENTS.md"})
    print(f"ok={r['ok']}")
    print(f"content preview: {r['content'][:200]}...")

    router.close()
    print("\nrouter closed cleanly")
