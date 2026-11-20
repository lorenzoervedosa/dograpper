# dograpper docs

Serve a **local reference site** for every command and option, generated at
run time from the installed CLI, so it always matches `--help`. One
self-contained page (no external stylesheet, script, font or image), so it
works offline and from the release binary. Each option has an anchor, for
example `#download--depth`.

```bash
dograpper docs                      # serves http://127.0.0.1:8000/ and opens the browser
dograpper docs --port 9000 --no-browser
```

Stop the server with Ctrl+C.

## Options

```{dograpper-options} docs
```

## Options in detail

### `--no-browser`

Only print the URL (always printed) instead of opening the browser
