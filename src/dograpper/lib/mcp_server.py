"""Minimal MCP (Model Context Protocol) server over stdio. Stdlib-only.

Implements the subset of MCP needed to expose tools to MCP clients
(Claude Code/Desktop, Cursor): initialize, ping, tools/list, tools/call,
over JSON-RPC 2.0 with newline-delimited messages on stdin/stdout.

No network I/O of any kind — the transport is stdio and every import is
stdlib. Auditable by reading this file's imports.

The protocol core (`McpServer.handle_message`) is transport-agnostic so
tests can drive it with plain dicts; `serve_stdio` is the thin loop.
"""

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

FALLBACK_PROTOCOL_VERSION = "2025-06-18"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ToolError(Exception):
    """Raised by a tool handler to report an in-band tool failure."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any]


class McpServer:
    def __init__(self, name: str, version: str, tools: List[Tool]):
        self.name = name
        self.version = version
        self.tools: Dict[str, Tool] = {t.name: t for t in tools}

    # -- JSON-RPC plumbing ---------------------------------------------------

    @staticmethod
    def _result(msg_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}}

    # -- Dispatch ------------------------------------------------------------

    def handle_message(self, msg: dict) -> Optional[dict]:
        """Handle one JSON-RPC message. Returns the response dict, or None
        for notifications (which must not be answered)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(None, INVALID_REQUEST, "Invalid JSON-RPC 2.0 message")

        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = "id" not in msg

        if not isinstance(method, str):
            return None if is_notification else self._error(
                msg_id, INVALID_REQUEST, "Missing method")

        params = msg.get("params")
        if params is not None and not isinstance(params, dict):
            return None if is_notification else self._error(
                msg_id, INVALID_PARAMS, "params must be an object")
        params = params or {}

        if method == "initialize":
            return self._result(msg_id, self._initialize(params))
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, self._tools_list())
        if method == "tools/call":
            return self._tools_call(msg_id, params)

        if is_notification:
            # e.g. notifications/initialized, notifications/cancelled
            return None
        return self._error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    # -- Methods -------------------------------------------------------------

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        protocol = requested if isinstance(requested, str) and requested \
            else FALLBACK_PROTOCOL_VERSION
        return {
            "protocolVersion": protocol,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.name, "version": self.version},
        }

    def _tools_list(self) -> dict:
        return {"tools": [
            {"name": t.name,
             "description": t.description,
             "inputSchema": t.input_schema}
            for t in self.tools.values()
        ]}

    def _tools_call(self, msg_id, params: dict) -> dict:
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return self._error(msg_id, INVALID_PARAMS, f"Unknown tool: {name}")

        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._error(msg_id, INVALID_PARAMS, "arguments must be an object")

        try:
            payload = tool.handler(arguments)
        except ToolError as e:
            return self._result(msg_id, {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            })
        except Exception as e:
            # A long-running server must survive buggy handlers/artifacts:
            # report loudly in-band instead of dying with a traceback.
            return self._error(
                msg_id, INTERNAL_ERROR,
                f"Internal error in tool '{name}': {type(e).__name__}: {e}")

        text = payload if isinstance(payload, str) else json.dumps(
            payload, indent=2, ensure_ascii=False)
        return self._result(msg_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        })


def serve_stdio(server: McpServer, stdin=None, stdout=None) -> None:
    """Blocking loop: one JSON-RPC message per line until EOF."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout

    def _write(response: dict) -> None:
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _write(McpServer._error(None, PARSE_ERROR, "Parse error"))
            continue
        response = server.handle_message(msg)
        if response is not None:
            _write(response)
