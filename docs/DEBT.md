# Accepted technical debt

Review findings accepted without a fix. Every item a review accepts without
fixing it lands here, with the reason and the condition that would make it
worth fixing. A fixed item is marked, not deleted.

Status markers: ⏸ accepted · ✅ fixed (link the commit or PR).

Entry format, grouped under one heading per issue or PR:

```markdown
## <topic> (#issue or PR, YYYY-MM-DD)

- **<finding in one sentence>.** <evidence: file:line, metric>. ⏸ **accepted:
  <why now is not the time>; <what would trigger the fix>.**
```

## Harness hooks (#35, 2026-11-18)

- **The contract file set lives in two places.** The `case` map of
  `.claude/hooks/harness-reminder.sh` and the regex of
  `.claude/hooks/commit-doc-check.sh` list the same files; each points at the
  other. ⏸ **accepted: two copies of a short list, pinned by
  `tests/test_claude_hooks.py`; extract a shared list file at the third
  consumer.**
- **A bare `git push` is checked against the session cwd.**
  `.claude/hooks/block-dangerous-git.py` reads the branch of the payload's
  `cwd` (plus any `git -C`), not of a `cd DIR &&` before the push, so a bare push from a worktree
  whose session sits on `main` is blocked by mistake. ⏸ **accepted: the
  message says to give the refspec, and agents here push with an explicit
  branch; fix if it blocks a real flow.**

## fire-engine body-size cap (ADR-0011, 2026-11-18)

- **The body cap is enforced in the consumer loop, not at curl's writer.**
  `src/dograpper/lib/fire_engine/fetcher.py` streams with `iter_content` and
  raises once `total > MAX_BODY_BYTES`, but curl_cffi can decode and buffer
  bytes ahead of the bandwidth-throttled drain, so peak allocation from a
  decompression bomb can pass the cap before the check fires. ⏸ **accepted: the
  consumer cap bounds the non-adversarial case, and the correct producer-side
  bound — disable curl's auto-decode and route the raw stream through
  `httrack.fetcher._decode` (already bounded), or a WRITEFUNCTION that aborts
  past the cap — must be verified against the real curl_cffi, which slice 1 does
  not install; fix it in the curl_cffi smoke-test slice.**
