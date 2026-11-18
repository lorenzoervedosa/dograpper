---
description: Lightweight recurring structural audit of the codebase (read-only)
---

Run a lightweight structural audit of dograpper. READ-ONLY: no code changes,
no issues opened and no `docs/DEBT.md` edits without asking. The only write
allowed is the log entry at the end.

Collect evidence with commands; never estimate:

1. **Size:** the 10 largest non-test modules in `src/dograpper`
   (`find src/dograpper -name '*.py' -print0 | xargs -0 wc -l | sort -rn`).
   Compare with the previous entry in `docs/audits/structural.md` and flag the
   files that grew.
2. **Churn:** the 5 files of `src/dograpper` with most commits in the last 4
   weeks (`git log --since='4 weeks ago' --name-only --pretty=format: --
   src/dograpper | sort | uniq -c | sort -rn`). Flag size × churn hotspots
   (big AND hot).
3. **Layering:** the import direction is `cli` → `commands/` → `lib/` →
   `utils/`. Flag any `utils/` module importing `lib/` or `commands/`, any
   `lib/` module importing `commands/`, and a generic `utils/` helper that
   knows about one feature.
4. **Duplication:** patterns at their 3rd hand-rolled copy (atomic writes
   that bypass `utils/atomic_write.py`, URL logging that bypasses
   `utils/redact.py`, local HTTP servers in tests, version lookups, file-name
   rules outside `utils/portable_names.py`). Start from the "second copy"
   markers: `git grep -n -i 'second copy' -- src tests`.
5. **Test harness:** test files over 1000 lines (`wc -l tests/*.py`), and new
   hand-rolled HTTP servers in tests that bypass the `server` fixture of
   `tests/conftest.py`.

Cross-check with the open issues (`gh issue list --state open`) and
`docs/DEBT.md`: do not re-report what an open issue or an accepted debt item
already covers; say instead whether a finding changes its priority.

Output: at most 5 findings, ranked by impact on agents working in the code
and by risk. Each finding needs concrete evidence (file:line, metric, count)
and one classification: **fix-now** (propose the change), **debt** (propose
the `docs/DEBT.md` entry text, do not write it) or **ignore** (say why). A
finding without evidence does not ship. If nothing is noteworthy, say
"nothing noteworthy" and stop before the findings list.

Finally, append a dated entry (5–10 lines: date, commit audited, headline
metrics, findings with classification) at the END of
`docs/audits/structural.md`. The log is append-only: never edit or delete a
previous entry.
