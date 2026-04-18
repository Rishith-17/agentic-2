"""Reusable async MCP (Model Context Protocol) client.

Windows fix: asyncio.create_subprocess_exec raises NotImplementedError on Windows
with uvicorn's ProactorEventLoop. We use a ThreadPoolExecutor + subprocess.Popen
(blocking) instead — the same pattern used for Playwright and pyttsx3.

Each call_tool() spawns the server process, sends one JSON-RPC request via stdin,
reads one JSON-RPC response from stdout, then terminates the process.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

# One shared pool — MCP calls are infrequent so 4 workers is plenty
_MCP_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp")


# ── Exceptions ────────────────────────────────────────────────────────────────

class MCPError(Exception):
    """Base exception for all MCP client errors."""


class MCPTimeoutError(MCPError):
    """Raised when an MCP call exceeds its timeout."""


class MCPProtocolError(MCPError):
    """Raised when the server returns malformed JSON-RPC."""


class MCPServerError(MCPError):
    """Raised when the server returns a JSON-RPC error object."""
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.data = data
        super().__init__(f"MCP server error {code}: {message}")


# ── Blocking worker (runs in thread pool) ─────────────────────────────────────

def _call_tool_sync(
    command: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    timeout: int,
    env: dict[str, str] | None,
    attempt: int,
) -> dict[str, Any]:
    """
    Blocking implementation of one MCP tool call.
    Spawns the server, sends JSON-RPC, reads response, kills server.
    Must only be called inside _MCP_EXECUTOR.
    """
    merged_env = {**os.environ, **(env or {})}
    request_id = str(uuid.uuid4())
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id":      request_id,
        "method":  "tools/call",
        "params":  {"name": tool_name, "arguments": arguments},
    }) + "\n"

    logger.debug("MCP[%d] -> %s %s", attempt, tool_name, payload.strip())

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            # Windows: don't open a console window
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise MCPError(f"MCP server command not found: {command[0]!r}. {exc}") from exc
    except Exception as exc:
        raise MCPError(f"Failed to start MCP server: {exc}") from exc

    try:
        try:
            stdout_bytes, stderr_bytes = proc.communicate(
                input=payload.encode(),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise MCPTimeoutError(
                f"MCP tool '{tool_name}' did not respond within {timeout}s"
            )

        if proc.returncode != 0 and not stdout_bytes.strip():
            stderr_text = stderr_bytes.decode(errors="replace")[:500]
            raise MCPError(
                f"MCP server exited with code {proc.returncode}. "
                f"stderr: {stderr_text}"
            )

        # Find the first non-empty JSON line in stdout
        raw_line = b""
        for line in stdout_bytes.splitlines():
            line = line.strip()
            if line.startswith(b"{"):
                raw_line = line
                break

        if not raw_line:
            stderr_text = stderr_bytes.decode(errors="replace")[:300]
            raise MCPProtocolError(
                f"MCP server produced no JSON output. "
                f"stdout: {stdout_bytes[:200]!r}  stderr: {stderr_text}"
            )

        logger.debug("MCP[%d] <- %s", attempt, raw_line.decode()[:200])

        try:
            response = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(
                f"MCP server returned non-JSON: {raw_line[:200]!r}"
            ) from exc

        if not isinstance(response, dict):
            raise MCPProtocolError(f"Expected JSON object, got {type(response)}")

        if response.get("id") is not None and response.get("id") != request_id:
            raise MCPProtocolError(
                f"Response ID mismatch: expected {request_id!r}, "
                f"got {response.get('id')!r}"
            )

        if "error" in response:
            err = response["error"]
            raise MCPServerError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )

        return response.get("result", {})

    finally:
        # Always clean up the process
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ── Async client ──────────────────────────────────────────────────────────────

class MCPClient:
    """
    Async context-manager for MCP tool calls.

    Each call_tool() runs the server in a thread so the event loop is never blocked.
    The context manager is kept for API compatibility — no persistent process is held.
    """

    def __init__(
        self,
        command: list[str],
        *,
        timeout: int = 30,
        max_retries: int = 2,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command     = command
        self._timeout     = timeout
        self._max_retries = max_retries
        self._env         = env

    async def __aenter__(self) -> "MCPClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass  # Nothing to clean up — processes are per-call

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        Call *tool_name* on the MCP server with *arguments*.
        Retries up to max_retries times on transient errors.
        """
        import asyncio
        effective_timeout = timeout or self._timeout
        last_exc: Exception | None = None
        loop = asyncio.get_event_loop()

        for attempt in range(1, self._max_retries + 2):
            try:
                result = await loop.run_in_executor(
                    _MCP_EXECUTOR,
                    _call_tool_sync,
                    self._command,
                    tool_name,
                    arguments,
                    effective_timeout,
                    self._env,
                    attempt,
                )
                return result

            except MCPServerError:
                raise  # Not retryable

            except MCPTimeoutError as exc:
                logger.warning(
                    "MCP '%s' timed out (attempt %d/%d)",
                    tool_name, attempt, self._max_retries + 1,
                )
                last_exc = exc

            except MCPProtocolError as exc:
                logger.warning(
                    "MCP protocol error on attempt %d: %s", attempt, exc
                )
                last_exc = exc

            except MCPError as exc:
                logger.warning(
                    "MCP error on attempt %d: %s", attempt, exc
                )
                last_exc = exc

        raise last_exc or MCPError("All MCP retry attempts exhausted")


# ── Convenience function ──────────────────────────────────────────────────────

async def call_tool(
    server_command: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout: int = 30,
    max_retries: int = 2,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One-shot helper: call a tool on an MCP server."""
    async with MCPClient(
        server_command, timeout=timeout, max_retries=max_retries, env=env
    ) as client:
        return await client.call_tool(tool_name, arguments, timeout=timeout)
