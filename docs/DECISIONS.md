# Session decisions

An operational log of the decisions an agent session took on its own: a choice
between two readings of a request, a deviation from the brief, a convention
picked where the repo had none, or a question left for the maintainer. It is
more granular than an ADR and cheaper to write.

- A decision that changes architecture or an inviolable contract (CLAUDE.md)
  goes to `docs/adr/` instead; an entry here can link the ADR it led to.
- A review finding accepted without a fix goes to `docs/DEBT.md`.
- Newest entry first. Never rewrite an old entry: add a new one that
  supersedes it and say so.

Entry format:

```markdown
## YYYY-MM-DD — <topic> (#issue or PR)

- **Decision:** <what was chosen>
- **Why:** <the evidence or constraint that decided it>
- **Rejected:** <the alternatives, one line each>
- **Pending:** <what the maintainer still has to answer, or "none">
```

## 2026-11-18 — Anti-bot evasion is no longer an anti-goal

- **Decision:** challenge or CAPTCHA solving, JavaScript challenge execution,
  browser TLS (JA3/JA4) or HTTP/2 fingerprint impersonation and proxy rotation
  are no longer anti-goals of dograpper. The `httrack` profile design listed
  them as "a failure even if it works". They are now a non-goal of that
  profile only, and another downloader may implement them.
- **Why:** maintainer decision. dograpper collects publicly available
  documentation, and its fetch paths already pace requests (connection rate,
  bandwidth, per-host gap, Retry-After, robots.txt). The target is scraping
  parity with Firecrawl-style engines.
- **Rejected:** dropping the exclusion from the `httrack` profile too. That
  profile's goal is behavior identical to HTTrack, which has none of these.
- **Pending:** confirm the `httrack` profile keeps them out, and design the
  downloader that adds them (an ADR first: a native dependency such as
  `curl_cffi` falls under contract 1).

## 2026-11-18 — Harness patterns mirrored from open-notes (#35)

- **Decision:** Phases 2–5 of the epic ship as one commit each in a single
  batch PR. Phase 1 (the `setup-matt-pocock-skills` skill) is left to the
  maintainer because it is interactive.
- **Why:** this repo's practice is one combined PR per batch of parallel
  sessions; the epic was written for one PR per phase.
- **Rejected:** one PR per phase (the batch flow already reviews them
  together).
- **Pending:** Phase 1.

- **Decision:** `block-dangerous-git.py` fails open on its own errors (bad
  JSON, an exception), unlike the open-notes original, which fails closed.
  An `--amend` whose repository it cannot tell is still blocked, as in the
  source, and so is a git command that does not tokenize (review finding):
  those are policy decisions, not errors.
- **Why:** a broken guard must never stop normal Bash work, and a hook that
  hangs is already let through by the harness timeout, so failing closed
  would only cover crashes.
- **Rejected:** fail closed (one crash would block every Bash call that
  mentions git).
- **Pending:** none.

- **Decision:** the push rule blocks any direct push to `main` or `develop`
  without user consent. There is no `GATES=green` attestation.
- **Why:** every change lands through a reviewed PR here; open-notes pushes to
  `main` after a local merge, which this repo never does.
- **Rejected:** porting the gates attestation as is.
- **Pending:** none.

- **Decision:** the living glossary is `docs/glossario.md` (pt-BR, didactic),
  separate from `GLOSSARY.md` (domain language, normative). A domain term is
  never redefined in `docs/glossario.md`; its entry points to `GLOSSARY.md`.
- **Why:** the `/explique` and `/revisao` commands read and write
  `docs/glossario.md` in a fixed format; `GLOSSARY.md` follows the
  domain-modeling format and names things in code.
- **Rejected:** merging both into `GLOSSARY.md` (two formats and two readers
  in one file).
- **Pending:** none.
