---
name: mcp-serve-inspect
description: Drive `dograpper serve` (the local MCP server over a JSONL pack) by hand over JSON-RPC on stdio — initialize, tools/list, search_chunks, get_chunk, get_cross_refs, get_readiness — and read the exact responses an MCP client would get. Use when a change to serve, the MCP protocol layer, retrieval or the JSONL pack format needs proof beyond pytest, or to see what a pack answers. NOT for fetching pages from a site (use the sibling skill download-smoke).
---

# Inspect `dograpper serve` over stdio

## When to use (and when not)

- **This skill:** the question is "what does an MCP client get from this
  pack": tool list, ranking of `search_chunks`, record fields, cross-refs,
  readiness, error shapes. Fully offline: the server makes no network call.
- **Sibling skill `download-smoke`:** the question involves fetching pages
  (cascade, wget, httrack profile). Use it first when the pack must come from
  a real download, then come back here with the packed directory.
- **Plain pytest:** protocol and tool unit behaviour is pinned in
  `tests/test_mcp_serve.py`; a session here is evidence on top of it.

## Procedure

1. Build a JSONL pack offline. The Javadoc fixture packs in about a second;
   use a fresh directory in the session scratchpad, never an existing pack:

   ```bash
   uv run dograpper pack tests/fixtures/javadoc/html -o "$SCRATCH/pack" \
     --format jsonl --context-header --cross-refs --score
   ```

   `--cross-refs` and `--score` write `cross_refs.json` and
   `llm-readiness.json`; without them `get_cross_refs` and `get_readiness`
   answer with an error. The "no manifest entry or page marker" warnings are
   expected for the fixture (it has no source URLs).

2. Send newline-delimited JSON-RPC 2.0 on stdin; the server answers one line
   per request on stdout, logs to stderr, and exits 0 at EOF:

   ```bash
   printf '%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"inspect","version":"0"}}}' \
     '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
     '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_chunks","arguments":{"query":"Box","k":3}}}' \
     '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_chunk","arguments":{"id":"01_fixture/api/Box.html"}}}' \
     '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_cross_refs","arguments":{"chunk_id":"docs_chunk_01"}}}' \
     '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"get_readiness","arguments":{}}}' \
     | uv run dograpper serve "$SCRATCH/pack" > "$SCRATCH/serve-out.jsonl" 2> "$SCRATCH/serve-err.txt"
   ```

   Redirect to files instead of piping into a filter, so `$?` is the
   server's.

3. Read the evidence:
   - stderr's first line: record count and whether cross-refs and readiness
     loaded (`9 records … (cross_refs: yes, readiness: yes)` for the fixture);
   - `initialize`: the negotiated `protocolVersion` (an unsupported one falls
     back to the default) and `serverInfo.version`;
   - `tools/list`: `search_chunks`, `get_chunk`, `get_cross_refs`,
     `get_readiness`;
   - each `tools/call` result is `{"content":[{"type":"text","text":"<JSON>"}]}`;
     parse `text` again. Tool errors (bad arguments, unknown id, missing
     sidecar) come back as a result with `"isError": true`; an unknown tool
     name is a JSON-RPC error `-32602`; a line that is not JSON is `-32700`.
   - the notification gets no answer.

   ```bash
   python3 -c 'import json, sys
   for line in open(sys.argv[1]):
       m = json.loads(line); r = m.get("result", {})
       body = r["content"][0]["text"] if "content" in r else json.dumps(m)
       print(m.get("id"), "isError" if r.get("isError") else "", body[:300])' "$SCRATCH/serve-out.jsonl"
   ```

4. To check a real client, register the same directory:
   `claude mcp add my-docs -- dograpper serve "$SCRATCH/pack"`, and remove it
   afterwards (`claude mcp remove my-docs`).

5. Report the requests, the exit code and the relevant responses. An empty
   pack directory makes `serve` exit 1 with a re-pack hint: that is a
   finding about the pack, not about the server.
