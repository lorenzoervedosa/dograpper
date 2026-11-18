---
name: download-smoke
description: Validate a real `dograpper download` end to end (the 4-layer discovery cascade, wget or the httrack profile, the manifest) against a local server first and at most one small allowed public site, without heavy or destructive crawls. Use when a change to download, discovery, wget, Playwright or the httrack profile needs proof beyond pytest. NOT for checking what an existing pack returns to an MCP client (use the sibling skill mcp-serve-inspect).
---

# Download smoke test

## When to use (and when not)

- **This skill:** the question is "does `download` fetch the right pages from
  a real server": which cascade layer wins, what wget or the httrack profile
  writes, what the manifest records, what a failure prints.
- **Sibling skill `mcp-serve-inspect`:** the pages are already packed and the
  question is what `dograpper serve` answers over JSON-RPC. No network.
- **Plain pytest:** unit behaviour (parsers, filters, retries, pacing). The
  suite already mocks wget and runs a local HTTP server
  (`tests/conftest.py`); a smoke run is evidence on top of it, not a
  replacement.

## Safety rules (inviolable)

- **Local first.** Every smoke starts against a local server (step 1). A
  public site is the exception, for a question only a real site answers.
- **Allowed sites only.** Before any public run, read the site's
  `robots.txt` and terms. A site that blocks AI crawlers (`ClaudeBot`,
  `anthropic-ai`) or forbids scraping is out, whatever the reason. The repo's
  reference site is `https://click.palletsprojects.com/en/stable/`.
- **Bounded and polite.** Public runs use `-d 1` and `--delay 500` or more.
  For the httrack profile: `--connections 1`, a low `--max-links`, and never
  `--no-robots` or `--disable-security-limits`. One run per question; read
  its log instead of re-crawling.
- **Fresh output.** Write to a new directory in the session scratchpad (or the
  gitignored `test-output/`). Never point `-o` at an existing mirror: the
  incremental manifest would be rewritten. Delete only directories you
  created in this session.
- **Free port.** Other sessions run servers too: let the OS pick the port.

## Procedure

1. Serve a local copy of the Javadoc fixture with a sitemap, on a free port.
   Copy it first; never write into `tests/fixtures/`.

   ```bash
   SITE="$SCRATCH/site"; cp -r tests/fixtures/javadoc/html "$SITE"
   PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
   { printf '<?xml version="1.0"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
     for f in $(cd "$SITE" && find fixture -name '*.html' | sort); do
       printf '<url><loc>http://127.0.0.1:%s/%s</loc></url>\n' "$PORT" "$f"; done
     printf '</urlset>\n'; } > "$SITE/sitemap.xml"
   python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SITE"   # run in background
   ```

   Drop the sitemap to exercise layer 3 (`wget --mirror`) instead of layer 2.

2. Run the download path under test, one fresh output directory per run:

   ```bash
   uv run dograpper download "http://127.0.0.1:$PORT/fixture/api/" -o "$SCRATCH/dl-wget" -d 2 --delay 200
   uv run dograpper download "http://127.0.0.1:$PORT/fixture/api/" -o "$SCRATCH/dl-httrack" \
     --downloader httrack --connections 1 --max-links 50
   ```

   Do not pipe these into `tail`/`grep` when the exit code matters (it would
   be the filter's).

3. Read the evidence:
   - the `[cascade]` lines: each layer's `raw=`/`in-scope=` counts and which
     one says `WIN`; with the fixture sitemap, layer 2 wins with 9 URLs;
   - the summary (`Files downloaded`, `Failed: N URLs` with the status of
     each);
   - the files under the output directory and its `.dograpper-manifest.json`
     (one entry per saved file, with the URL it was requested from);
   - for the httrack profile, its run report (counts per status, robots,
     out-of-scope, errors). Check `download --help` and the README for what the
     profile fetches without a seed list: it changes as the profile grows.

4. Optional, to connect with packing: `uv run dograpper pack "$SCRATCH/dl-wget" -o "$SCRATCH/pack" --dry-run`.

5. Stop the server (`pkill -f "http.server $PORT"`) and report the commands,
   the exit codes and the evidence above. A smoke that was not run is not
   evidence.
