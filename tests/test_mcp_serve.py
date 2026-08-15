"""Tests for the MCP server: protocol core, tools, stdio loop, CLI."""

import io
import json
import os

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.mcp_server import (
    McpServer,
    Tool,
    ToolError,
    serve_stdio,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)
from dograpper.lib.pack_reader import load_chunks
from dograpper.lib.retrieval import build_index
from dograpper.commands.serve import build_tools, _parent_chunk_id


def _make_server(tools=None):
    return McpServer(name="dograpper", version="0.0.0-test", tools=tools or [])


def _req(method, msg_id=1, params=None):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


# ---------------------------------------------------------------------------
# Protocol core
# ---------------------------------------------------------------------------

def test_initialize_echoes_protocol_version():
    server = _make_server()
    resp = server.handle_message(_req("initialize", params={
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    }))
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "dograpper"
    assert "tools" in result["capabilities"]


def test_initialize_without_version_uses_fallback():
    server = _make_server()
    resp = server.handle_message(_req("initialize", params={}))
    assert resp["result"]["protocolVersion"]


def test_initialize_unknown_version_gets_fallback_not_echo():
    server = _make_server()
    resp = server.handle_message(_req("initialize", params={
        "protocolVersion": "banana"}))
    assert resp["result"]["protocolVersion"] == "2025-06-18"


def test_ping_returns_empty_result():
    server = _make_server()
    resp = server.handle_message(_req("ping"))
    assert resp["result"] == {}


def test_initialized_notification_gets_no_response():
    server = _make_server()
    resp = server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


def test_unknown_method_with_id_errors():
    server = _make_server()
    resp = server.handle_message(_req("resources/list"))
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_unknown_notification_ignored():
    server = _make_server()
    resp = server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/cancelled"})
    assert resp is None


def test_handled_methods_as_notifications_get_no_response():
    server = _make_server()
    for method in ("ping", "initialize", "tools/list", "tools/call"):
        resp = server.handle_message({"jsonrpc": "2.0", "method": method})
        assert resp is None, method


def test_non_jsonrpc_message_rejected():
    server = _make_server()
    resp = server.handle_message({"id": 1, "method": "initialize"})
    assert resp["error"]["code"] == -32600
    # a detectable id is preserved on the error, per JSON-RPC 2.0
    assert resp["id"] == 1


def test_tools_list_exposes_schema():
    tool = Tool(name="echo", description="Echo.",
                input_schema={"type": "object"}, handler=lambda a: a)
    server = _make_server([tool])
    resp = server.handle_message(_req("tools/list"))
    tools = resp["result"]["tools"]
    assert tools == [{"name": "echo", "description": "Echo.",
                      "inputSchema": {"type": "object"}}]


def test_tools_call_success_wraps_text_content():
    tool = Tool(name="greet", description="", input_schema={},
                handler=lambda a: {"hello": a.get("who", "world")})
    server = _make_server([tool])
    resp = server.handle_message(_req("tools/call", params={
        "name": "greet", "arguments": {"who": "claude"}}))
    result = resp["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"hello": "claude"}


def test_tools_call_unknown_tool_is_invalid_params():
    server = _make_server()
    resp = server.handle_message(_req("tools/call", params={"name": "nope"}))
    assert resp["error"]["code"] == INVALID_PARAMS


def test_non_dict_params_is_error_not_crash():
    server = _make_server()
    for bad_params in ("x", ["a"], 42):
        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": bad_params})
        assert resp["error"]["code"] == INVALID_PARAMS
        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": bad_params})
        assert resp["error"]["code"] == INVALID_PARAMS
    # notification with bad params: ignored, no crash, no response
    resp = server.handle_message({
        "jsonrpc": "2.0", "method": "notifications/initialized",
        "params": "x"})
    assert resp is None


def test_handler_crash_becomes_internal_error():
    def boom(args):
        raise KeyError("oops")
    tool = Tool(name="boom", description="", input_schema={}, handler=boom)
    server = _make_server([tool])
    resp = server.handle_message(_req("tools/call", params={"name": "boom"}))
    assert resp["error"]["code"] == INTERNAL_ERROR
    assert "boom" in resp["error"]["message"]
    # server object remains usable
    assert server.handle_message(_req("ping", msg_id=9))["result"] == {}


def test_tools_call_tool_error_is_in_band():
    def boom(args):
        raise ToolError("missing thing")
    tool = Tool(name="boom", description="", input_schema={}, handler=boom)
    server = _make_server([tool])
    resp = server.handle_message(_req("tools/call", params={"name": "boom"}))
    result = resp["result"]
    assert result["isError"] is True
    assert "missing thing" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# stdio loop
# ---------------------------------------------------------------------------

def test_serve_stdio_roundtrip_and_parse_error():
    server = _make_server()
    lines = "\n".join([
        json.dumps(_req("initialize", msg_id=0,
                        params={"protocolVersion": "2024-11-05"})),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "this is not json",
        "",
        json.dumps(_req("ping", msg_id=2)),
    ]) + "\n"
    stdout = io.StringIO()
    serve_stdio(server, stdin=io.StringIO(lines), stdout=stdout)

    responses = [json.loads(l) for l in stdout.getvalue().splitlines()]
    # initialize + parse error + ping (notification and blank line: no output)
    assert len(responses) == 3
    assert responses[0]["id"] == 0
    assert responses[1]["error"]["code"] == PARSE_ERROR
    assert responses[2]["id"] == 2


def test_serve_stdio_survives_handler_crash_and_bad_params():
    def boom(args):
        raise RuntimeError("handler bug")
    tool = Tool(name="boom", description="", input_schema={}, handler=boom)
    server = _make_server([tool])
    lines = "\n".join([
        json.dumps(_req("tools/call", msg_id=0, params={"name": "boom"})),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": "not-an-object"}),
        json.dumps(_req("ping", msg_id=2)),
    ]) + "\n"
    stdout = io.StringIO()
    serve_stdio(server, stdin=io.StringIO(lines), stdout=stdout)

    responses = [json.loads(l) for l in stdout.getvalue().splitlines()]
    assert len(responses) == 3
    assert responses[0]["error"]["code"] == INTERNAL_ERROR
    assert responses[1]["error"]["code"] == INVALID_PARAMS
    assert responses[2]["result"] == {}  # server still alive after both


# ---------------------------------------------------------------------------
# Pack-backed tools
# ---------------------------------------------------------------------------

def _write_pack(tmp_path):
    records = [
        {"id": "00_guide/intro.html", "source": "guide/intro.html",
         "words": 8, "content": "Introduction to the dograpper pipeline basics.",
         "breadcrumb": ["Guide", "Intro"], "readiness_grade": "A",
         "schema_version": "v1"},
        {"id": "00_guide/config.html", "source": "guide/config.html",
         "words": 7, "content": "Configuration precedence and json settings.",
         "breadcrumb": ["Guide", "Config"], "readiness_grade": "B",
         "schema_version": "v1"},
    ]
    with open(os.path.join(tmp_path, "docs_chunk_00.jsonl"), "w",
              encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(tmp_path, "cross_refs.json"), "w",
              encoding="utf-8") as f:
        json.dump({"docs_chunk_00": {"references_to": ["docs_chunk_01"],
                                     "referenced_by": [], "links": []}}, f)
    with open(os.path.join(tmp_path, "llm-readiness.json"), "w",
              encoding="utf-8") as f:
        json.dump({"summary": {"total_chunks": 1, "avg_score": 90.0,
                               "grades": {"A": 1, "B": 0, "C": 0}},
                   "chunks": [{"chunk_id": "docs_chunk_00", "score": 90.0,
                               "grade": "A", "noise_ratio": 0.1,
                               "boundary_integrity": True,
                               "context_depth": 2, "word_count": 15}]}, f)


def _pack_server(tmp_path):
    _write_pack(str(tmp_path))
    chunks = load_chunks(str(tmp_path))
    index = build_index(chunks)
    with open(os.path.join(str(tmp_path), "cross_refs.json"), encoding="utf-8") as f:
        cross = json.load(f)
    with open(os.path.join(str(tmp_path), "llm-readiness.json"), encoding="utf-8") as f:
        readiness = json.load(f)
    tools = build_tools(chunks, index, cross, readiness, "docs_chunk_")
    return _make_server(tools)


def _call(server, name, arguments):
    resp = server.handle_message(_req("tools/call", params={
        "name": name, "arguments": arguments}))
    result = resp["result"]
    return result["isError"], result["content"][0]["text"]


def test_search_chunks_deterministic_ranked_results(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "search_chunks",
                         {"query": "configuration precedence"})
    assert is_err is False
    payload = json.loads(text)
    assert payload["results"][0]["id"] == "00_guide/config.html"
    assert payload["results"][0]["chunk_id"] == "docs_chunk_00"
    assert payload["results"][0]["grade"] == "B"
    assert payload["results"][0]["breadcrumb"] == ["Guide", "Config"]

    _, text2 = _call(server, "search_chunks",
                     {"query": "configuration precedence"})
    assert text == text2  # deterministic


def test_search_chunks_requires_query(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "search_chunks", {})
    assert is_err is True
    assert "query" in text


def test_search_chunks_respects_k(tmp_path):
    server = _pack_server(tmp_path)
    # both records contain "the"; k must cap the matches
    _, text = _call(server, "search_chunks",
                    {"query": "configuration pipeline", "k": 1})
    assert len(json.loads(text)["results"]) == 1


def test_search_chunks_rejects_boolean_k(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "search_chunks",
                         {"query": "pipeline", "k": True})
    assert is_err is True
    assert "positive integer" in text


def test_search_chunks_no_match_returns_empty(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "search_chunks",
                         {"query": "zzz nonexistent qqq"})
    assert is_err is False
    assert json.loads(text)["results"] == []


def test_get_chunk_full_content(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "get_chunk", {"id": "00_guide/intro.html"})
    assert is_err is False
    payload = json.loads(text)
    assert payload["content"] == "Introduction to the dograpper pipeline basics."
    assert payload["chunk_id"] == "docs_chunk_00"


def test_get_chunk_not_found(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "get_chunk", {"id": "missing"})
    assert is_err is True
    assert "not found" in text.lower()


def test_get_cross_refs(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "get_cross_refs", {"chunk_id": "docs_chunk_00"})
    assert is_err is False
    assert json.loads(text)["references_to"] == ["docs_chunk_01"]


def test_get_cross_refs_unknown_chunk(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "get_cross_refs", {"chunk_id": "docs_chunk_99"})
    assert is_err is True


def test_get_readiness_per_chunk_and_summary(tmp_path):
    server = _pack_server(tmp_path)
    is_err, text = _call(server, "get_readiness", {"chunk_id": "docs_chunk_00"})
    assert is_err is False
    assert json.loads(text)["grade"] == "A"

    is_err, text = _call(server, "get_readiness", {})
    assert is_err is False
    assert json.loads(text)["total_chunks"] == 1


def test_missing_sidecars_reported_in_band(tmp_path):
    _write_pack(str(tmp_path))
    chunks = load_chunks(str(tmp_path))
    index = build_index(chunks)
    tools = build_tools(chunks, index, None, None, "docs_chunk_")
    server = _make_server(tools)

    is_err, text = _call(server, "get_cross_refs", {"chunk_id": "docs_chunk_00"})
    assert is_err is True
    assert "--cross-refs" in text

    is_err, text = _call(server, "get_readiness", {})
    assert is_err is True
    assert "--score" in text


def test_malformed_sidecar_shape_reported_not_fatal(tmp_path):
    # A hand-edited cross_refs.json with a non-dict entry must not kill the
    # long-running server: the call errors in-band, the next call works.
    _write_pack(str(tmp_path))
    chunks = load_chunks(str(tmp_path))
    index = build_index(chunks)
    tools = build_tools(chunks, index, {"docs_chunk_00": ["broken"]}, None,
                        "docs_chunk_")
    server = _make_server(tools)
    resp = server.handle_message(_req("tools/call", params={
        "name": "get_cross_refs", "arguments": {"chunk_id": "docs_chunk_00"}}))
    assert resp["error"]["code"] == INTERNAL_ERROR
    resp = server.handle_message(_req("tools/call", msg_id=2, params={
        "name": "search_chunks", "arguments": {"query": "guide"}}))
    assert resp["result"]["isError"] is False


def test_parent_chunk_id_mapping():
    assert _parent_chunk_id("00_guide/intro.html", "docs_chunk_") == "docs_chunk_00"
    assert _parent_chunk_id("03_2_a/b.html", "docs_chunk_") == "docs_chunk_03"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_serve_cli_empty_dir_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("empty")
        result = runner.invoke(cli, ["serve", "empty"])
        assert result.exit_code == 1
        assert "no JSONL chunks" in result.output


def test_serve_cli_protocol_roundtrip(tmp_path):
    _write_pack(str(tmp_path))
    stdin_payload = "\n".join([
        json.dumps(_req("initialize", msg_id=0,
                        params={"protocolVersion": "2024-11-05"})),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(_req("tools/list", msg_id=1)),
        json.dumps(_req("tools/call", msg_id=2, params={
            "name": "search_chunks",
            "arguments": {"query": "configuration"}})),
    ]) + "\n"
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", str(tmp_path)], input=stdin_payload)
    assert result.exit_code == 0, result.output
    # result.output merges stdout and stderr; the protocol responses are
    # the JSON lines, the status message goes to stderr
    protocol_lines = [l for l in result.output.splitlines()
                      if l.startswith("{")]
    assert len(protocol_lines) == 3
    init_resp = json.loads(protocol_lines[0])
    assert init_resp["result"]["serverInfo"]["name"] == "dograpper"
    tools_resp = json.loads(protocol_lines[1])
    names = {t["name"] for t in tools_resp["result"]["tools"]}
    assert names == {"search_chunks", "get_chunk", "get_cross_refs",
                     "get_readiness"}
    call_resp = json.loads(protocol_lines[2])
    assert call_resp["result"]["isError"] is False
