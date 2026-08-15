"""Context drift between two llm-readiness.json snapshots.

Pure stdlib module (no click): compares readiness snapshots keyed by
``chunk_id`` and renders a human-readable drift report (markdown or plain
text) for the `dograpper drift` subcommand and the freshness GitHub Action.

Caveat: chunk ids are positional (``docs_chunk_NN``) and can be renumbered
by upstream content changes, so chunk-level drift is best-effort; the
delta_manifest.json file lists are exact.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ChunkRef:
    """A chunk present on only one side of the diff."""
    chunk_id: str
    score: float
    grade: str


@dataclass
class ChunkChange:
    """A chunk present on both sides with a different grade or score."""
    chunk_id: str
    old_score: float
    new_score: float
    old_grade: str
    new_grade: str


@dataclass
class DriftReport:
    first_run: bool
    added: List[ChunkRef]
    modified: List[ChunkChange]
    removed: List[ChunkRef]
    old_avg_score: Optional[float]
    new_avg_score: Optional[float]

    @property
    def has_drift(self) -> bool:
        return self.first_run or bool(self.added or self.modified or self.removed)


def _by_id(snapshot: dict) -> dict:
    return {c["chunk_id"]: c for c in snapshot.get("chunks", [])}


def _avg_score(chunks_by_id: dict) -> Optional[float]:
    if not chunks_by_id:
        return None
    total = sum(float(c["score"]) for c in chunks_by_id.values())
    return round(total / len(chunks_by_id), 2)


def compare_readiness(old: Optional[dict], new: dict) -> DriftReport:
    """Diff two llm-readiness.json dicts keyed by chunk_id.

    ``old=None`` means first run: every chunk in ``new`` is reported as
    added. All lists are sorted by chunk_id ascending.
    """
    new_by_id = _by_id(new)
    old_by_id = {} if old is None else _by_id(old)

    added = [
        ChunkRef(cid, float(c["score"]), c["grade"])
        for cid, c in new_by_id.items() if cid not in old_by_id
    ]
    removed = [
        ChunkRef(cid, float(c["score"]), c["grade"])
        for cid, c in old_by_id.items() if cid not in new_by_id
    ]
    modified = []
    for cid in new_by_id:
        if cid not in old_by_id:
            continue
        old_c, new_c = old_by_id[cid], new_by_id[cid]
        if old_c["grade"] != new_c["grade"] or float(old_c["score"]) != float(new_c["score"]):
            modified.append(ChunkChange(
                chunk_id=cid,
                old_score=float(old_c["score"]),
                new_score=float(new_c["score"]),
                old_grade=old_c["grade"],
                new_grade=new_c["grade"],
            ))

    return DriftReport(
        first_run=old is None,
        added=sorted(added, key=lambda c: c.chunk_id),
        modified=sorted(modified, key=lambda c: c.chunk_id),
        removed=sorted(removed, key=lambda c: c.chunk_id),
        old_avg_score=_avg_score(old_by_id) if old is not None else None,
        new_avg_score=_avg_score(new_by_id),
    )


def _fmt_avg(avg: Optional[float]) -> str:
    return "n/a" if avg is None else f"{avg:.2f}"


def _summary_counts(report: DriftReport) -> str:
    return (f"{len(report.added)} added, {len(report.modified)} modified, "
            f"{len(report.removed)} removed")


def _delta_file_groups(delta: dict):
    """Added/Modified/Removed path lists from a delta_manifest.json dict,
    each sorted ascending. Shared by both renderers."""
    return [(label, sorted(delta.get(key, [])))
            for label, key in (("Added", "added"),
                               ("Modified", "modified"),
                               ("Removed", "removed"))]


def render_markdown(report: DriftReport, delta: Optional[dict] = None) -> str:
    """Render the drift report as markdown (PR-comment friendly).

    The first line is always the ``<!-- dograpper-drift -->`` marker, used
    by the GitHub Action to upsert its comment. ``delta`` is the parsed
    delta_manifest.json; when None the source-file section is omitted
    entirely (the Action appends its own git-based section instead).
    """
    lines = ["<!-- dograpper-drift -->", "## Context drift report", ""]

    if report.first_run:
        lines.append("**First run** — no previous snapshot; "
                     "every chunk is reported as added.")
        lines.append("")

    avg = f"avg score {_fmt_avg(report.old_avg_score)} → {_fmt_avg(report.new_avg_score)}"
    if report.has_drift:
        lines.append(f"**Summary:** {_summary_counts(report)} — {avg}")
    else:
        lines.append(f"**Summary:** no drift — {avg}")

    if report.added:
        lines += ["", f"### Added chunks ({len(report.added)})", ""]
        lines += [f"- `{c.chunk_id}` — score {c.score:.2f}, grade {c.grade}"
                  for c in report.added]
    if report.modified:
        lines += ["", f"### Modified chunks ({len(report.modified)})", ""]
        lines += [f"- `{c.chunk_id}` — grade {c.old_grade} → {c.new_grade}, "
                  f"score {c.old_score:.2f} → {c.new_score:.2f} "
                  f"({c.new_score - c.old_score:+.2f})"
                  for c in report.modified]
    if report.removed:
        lines += ["", f"### Removed chunks ({len(report.removed)})", ""]
        lines += [f"- `{c.chunk_id}` — score {c.score:.2f}, grade {c.grade}"
                  for c in report.removed]

    if delta is not None:
        lines += ["", "### Source file drift", ""]
        groups = _delta_file_groups(delta)
        if not any(paths for _, paths in groups):
            lines.append("_No source file changes._")
        else:
            for label, paths in groups:
                if not paths:
                    continue
                lines += [f"**{label} files ({len(paths)})**", ""]
                lines += [f"- `{p}`" for p in paths]
                lines.append("")
            lines.pop()  # trailing blank line

    return "\n".join(lines)


def render_text(report: DriftReport, delta: Optional[dict] = None) -> str:
    """Render the drift report as plain text (terminal friendly)."""
    title = "Context drift report"
    lines = [title, "=" * len(title)]

    if report.first_run:
        lines.append("First run — no previous snapshot; "
                     "every chunk is reported as added.")

    avg = (f"avg score {_fmt_avg(report.old_avg_score)} -> "
           f"{_fmt_avg(report.new_avg_score)}")
    if report.has_drift:
        lines.append(f"Summary: {_summary_counts(report)} | {avg}")
    else:
        lines.append(f"Summary: no drift | {avg}")

    if report.added:
        lines += ["", f"Added chunks ({len(report.added)}):"]
        lines += [f"  {c.chunk_id}  score {c.score:.2f}  grade {c.grade}"
                  for c in report.added]
    if report.modified:
        lines += ["", f"Modified chunks ({len(report.modified)}):"]
        lines += [f"  {c.chunk_id}  grade {c.old_grade} -> {c.new_grade}  "
                  f"score {c.old_score:.2f} -> {c.new_score:.2f} "
                  f"({c.new_score - c.old_score:+.2f})"
                  for c in report.modified]
    if report.removed:
        lines += ["", f"Removed chunks ({len(report.removed)}):"]
        lines += [f"  {c.chunk_id}  score {c.score:.2f}  grade {c.grade}"
                  for c in report.removed]

    if delta is not None:
        lines.append("")
        groups = _delta_file_groups(delta)
        if not any(paths for _, paths in groups):
            lines.append("Source file drift: no source file changes")
        else:
            lines.append("Source file drift:")
            for label, paths in groups:
                if not paths:
                    continue
                lines.append(f"  {label} files ({len(paths)}):")
                lines += [f"    {p}" for p in paths]

    return "\n".join(lines)
