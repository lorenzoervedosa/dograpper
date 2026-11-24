# Manual checks

Checks only a person can run, because they need a real browser and a display, an
account on another service, or a judgement call. Tests and CI cannot run them.
Each pending check is listed here with the condition that makes it due.

- A done check is marked, not deleted.
- When a check fails, its entry links the issue opened for the failure.

Status markers: ⏳ pending · ✅ done (date, result, link) · ❌ failed (link the issue).

Entry format, one heading per check:

```markdown
## <what to check> (#issue, YYYY-MM-DD)

- **Due:** <the event that makes it runnable, e.g. "after #N merges">
- **Why manual:** <what automated tests cannot reach>
- **How:** <steps, with exact commands>
- **Pass when:** <the observable result>
- ⏳ **pending**
```

## Real headed login with `--browser-login` (#171, 2026-11-20)

- **Due:** after #171 (PR 5, slice C of #78) merges.
- **Why manual:**
  - the flag opens a headed Chromium on the start URL and waits for a person to log in, or to pass a challenge, and press Enter;
  - CI has no browser or display, and the tests drive Playwright doubles.
- **How:**
  1. Pick a site that needs a login and that you may mirror.
  2. Run `uv run dograpper download <start-url> --downloader httrack --browser-login --cookies ./cookies.txt -o ./mirror -d 1`, using the flag spelling #171 ships.
  3. Log in in the window that opens, then press Enter in the terminal.
  4. Run again without `--browser-login`, with `--cookies ./cookies.txt` only.
- **Pass when:**
  - the first run saves pages that are behind the login;
  - `cookies.txt` holds the session cookies, with no cookie value printed in the terminal or the report;
  - the second run reaches the same pages with no new login.
- ⏳ **pending**

## Report the `chrome131_android` mobile client hint upstream (#157, 2026-11-20)

- **Due:** now.
- **Why manual:** it is an issue in another project, filed from the maintainer's account.
- **How:**
  1. Open an issue at `https://github.com/lexiforest/curl_cffi/issues`. The target's headers are compiled into the libcurl-impersonate that curl_cffi bundles, so the maintainers may move it to `lexiforest/curl-impersonate`.
  2. In the issue, state that `impersonate="chrome131_android"` (curl_cffi 0.17.0) sends `sec-ch-ua-mobile: ?0` with an Android Chrome 131 User-Agent and `sec-ch-ua-platform: "Android"`.
  3. Add the expected value: `?1`, which `chrome99_android` already sends.
  4. Add the reproduction: one request to a local socket server that prints the raw request head.
- **Pass when:** the upstream issue exists and is linked on #157. dograpper already overrides the value (#184).
- ✅ **done** (2026-11-24): [lexiforest/curl_cffi#911](https://github.com/lexiforest/curl_cffi/issues/911), linked on #157.
