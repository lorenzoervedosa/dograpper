# HTTrack 3.51 wire fixtures

`httrack_3.51_requests.json` pins what HTTrack puts on the wire: three
records (`robots`, `start`, `linked`), each with the HTTP `request_line`, the
ordered `headers` list (verbatim) and the parsed TLS `client_hello`.
Captured values are never hand-edited.

Captured on 2026-11-14 with `httrack.exe` 3.51-0 (WinHTTrack, bundled
OpenSSL 3.6.5) run from WSL2 against `capture.py` on a throwaway
self-signed localhost certificate (not committed; generate your own).
`/` links to `/a.html`; `/robots.txt` returns 404.

## Regenerate

```bash
T=$(mktemp -d)
openssl req -x509 -newkey rsa:2048 -nodes -keyout $T/key.pem -out $T/cert.pem \
  -days 2 -subj /CN=localhost -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
python3 -I capture.py 8443 $T/cert.pem $T/key.pem $T/out.jsonl &
"/mnt/c/Program Files/WinHTTrack/httrack.exe" "https://localhost:8443/" \
  -O 'C:\Users\<you>\AppData\Local\Temp\ht_fix' -r3 -q
kill %1
```

`out.jsonl` then holds one record per connection, in order: robots, start,
linked. Keep `request_line`, `headers`, `client_hello` of each.
