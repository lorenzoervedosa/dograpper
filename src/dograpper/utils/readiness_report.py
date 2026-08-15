"""Readiness report generation for the pack command (--report).

Receives per-chunk scores and per-page extraction data and produces a
self-contained HTML report plus a colorized terminal summary. Pure
string builders: no I/O and no click.echo inside generation.
"""

import html as html_mod
from dataclasses import dataclass, field
from typing import Dict, List

import click

REMOVED_SAMPLES_PER_PAGE = 5
SAMPLE_MAX_CHARS = 200


@dataclass
class PageReadiness:
    """Per-source-page extraction data collected during scoring."""
    relative_path: str
    raw_words: int
    extracted_words: int
    noise_ratio: float
    headings_count: int = 0
    max_heading_level: int = 0
    first_headings: List[str] = field(default_factory=list)
    removed_samples: List[str] = field(default_factory=list)


def find_removed_blocks(
    raw_text: str,
    extracted_text: str,
    max_samples: int = REMOVED_SAMPLES_PER_PAGE,
    max_chars: int = SAMPLE_MAX_CHARS,
) -> List[str]:
    """Blocks present in the raw text but absent from the extracted text.

    Blocks are split on \\n\\n and compared as stripped strings; blocks
    removed by extraction are returned in document order, capped at
    max_samples and truncated to max_chars each.
    """
    extracted_blocks = {b.strip() for b in extracted_text.split("\n\n")}
    removed = [
        b.strip() for b in raw_text.split("\n\n")
        if b.strip() and b.strip() not in extracted_blocks
    ]
    return [b[:max_chars] for b in removed[:max_samples]]


def _esc(value) -> str:
    """Escape document-derived text for HTML embedding.

    Security invariant: every piece of scraped content in the report
    must go through this helper — never embed raw document text.
    """
    return html_mod.escape(str(value))


def _sort_worst_first(scores: list) -> list:
    """Score ascending (C chunks on top), tie-break chunk_id ascending."""
    return sorted(scores, key=lambda s: (s.score, s.chunk_id))


_REPORT_CSS = """
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
       margin: 2rem auto; max-width: 60rem; padding: 0 1rem;
       color: #1a1a2e; background: #fafafa; }
h1 { font-size: 1.5rem; }
.summary { background: #fff; border: 1px solid #ddd; border-radius: 6px;
           padding: 1rem; margin-bottom: 1.5rem; }
.chunk { background: #fff; border: 1px solid #ddd; border-radius: 6px;
         padding: 1rem; margin-bottom: 1rem; }
.grade { display: inline-block; min-width: 1.6rem; text-align: center;
         border-radius: 4px; padding: 0.1rem 0.4rem; color: #fff;
         font-weight: bold; }
.grade-a { background: #2e8b57; }
.grade-b { background: #e8960c; }
.grade-c { background: #cc3333; }
table { border-collapse: collapse; margin: 0.5rem 0; }
th, td { border: 1px solid #ddd; padding: 0.3rem 0.6rem; text-align: left; }
th { background: #f0f0f0; }
.penalty { margin: 0.8rem 0 0.3rem; font-weight: bold; }
.sample { background: #f6f6f6; border-left: 3px solid #ccc;
          padding: 0.3rem 0.6rem; margin: 0.3rem 0; font-size: 0.85rem;
          white-space: pre-wrap; word-break: break-word; }
.issue { color: #cc3333; font-family: monospace; font-size: 0.85rem; }
.muted { color: #777; }
"""


def _grade_badge(grade: str) -> str:
    return f'<span class="grade grade-{grade.lower()}">{_esc(grade)}</span>'


def generate_html_report(
    scores: list,
    pages_by_chunk: Dict[str, List[PageReadiness]],
    issues_by_chunk: dict,
) -> str:
    """Build the self-contained HTML readiness report as a string.

    scores: list of ChunkScore; pages_by_chunk / issues_by_chunk map
    chunk_id to its PageReadiness list / BoundaryIssue list.
    """
    ordered = _sort_worst_first(scores)
    avg_score = sum(s.score for s in scores) / len(scores) if scores else 0.0
    grade_counts = {"A": 0, "B": 0, "C": 0}
    for s in scores:
        grade_counts[s.grade] += 1

    out = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en">')
    out.append("<head>")
    out.append('<meta charset="utf-8">')
    out.append("<title>LLM Readiness Report</title>")
    out.append(f"<style>{_REPORT_CSS}</style>")
    out.append("</head>")
    out.append("<body>")
    out.append("<h1>LLM Readiness Report</h1>")

    # --- Summary header ---
    out.append('<div class="summary">')
    out.append(f"<p>Total chunks: <strong>{len(scores)}</strong> &mdash; "
               f"Average score: <strong>{avg_score:.2f}</strong></p>")
    out.append("<p>"
               + " ".join(f"{_grade_badge(g)} {grade_counts[g]}" for g in ("A", "B", "C"))
               + "</p>")
    out.append("<p class=\"muted\">Chunks sorted worst-first: fix the top ones first.</p>")
    out.append("</div>")

    # --- Per chunk, worst-first ---
    for s in ordered:
        pages = pages_by_chunk.get(s.chunk_id, [])
        issues = issues_by_chunk.get(s.chunk_id, [])

        out.append('<div class="chunk">')
        out.append(f"<h2>{_esc(s.chunk_id)} {_grade_badge(s.grade)} "
                   f"<small>score {s.score:.2f}</small></h2>")

        # Noise penalty: per-page before/after + removed samples
        out.append(f'<p class="penalty">Noise ratio: {s.noise_ratio:.1%}</p>')
        if pages:
            out.append("<table>")
            out.append("<tr><th>Page</th><th>Raw words</th>"
                       "<th>Extracted words</th><th>Noise</th></tr>")
            for p in pages:
                out.append(
                    f"<tr><td>{_esc(p.relative_path)}</td>"
                    f"<td>{p.raw_words:,}</td>"
                    f"<td>{p.extracted_words:,}</td>"
                    f"<td>{p.noise_ratio:.1%}</td></tr>"
                )
            out.append("</table>")
            for p in pages:
                if p.removed_samples:
                    out.append(f"<p>Removed from {_esc(p.relative_path)}:</p>")
                    for sample in p.removed_samples:
                        out.append(f'<div class="sample">{_esc(sample)}</div>')
        else:
            out.append('<p class="muted">No per-page data collected.</p>')

        # Boundary penalty: issue locations/snippets
        boundary_label = "OK" if s.boundary_integrity else "BROKEN"
        out.append(f'<p class="penalty">Boundary integrity: {boundary_label}</p>')
        if issues:
            for issue in issues:
                out.append(
                    f'<p class="issue">{_esc(issue.kind)} at line {issue.line}: '
                    f"{_esc(issue.snippet)}</p>"
                )
        else:
            out.append('<p class="muted">No broken blocks detected.</p>')

        # Context depth penalty: headings found (or absence)
        out.append(f'<p class="penalty">Context depth: {s.context_depth}</p>')
        heading_lines = []
        for p in pages:
            if p.headings_count > 0:
                firsts = ", ".join(_esc(h) for h in p.first_headings)
                heading_lines.append(
                    f"<li>{_esc(p.relative_path)}: {p.headings_count} headings "
                    f"(max level h{p.max_heading_level}) &mdash; {firsts}</li>"
                )
        if heading_lines:
            out.append("<ul>" + "".join(heading_lines) + "</ul>")
        else:
            out.append('<p class="muted">No headings found.</p>')

        out.append("</div>")

    out.append("</body>")
    out.append("</html>")
    return "\n".join(out)


_GRADE_COLORS = {"A": "green", "B": "yellow", "C": "red"}


def _dominant_penalty(s) -> str:
    """Name of the penalty that costs the chunk the most score."""
    if s.context_depth >= 2:
        context_penalty = 0.0
    elif s.context_depth == 1:
        context_penalty = 0.15
    else:
        context_penalty = 0.3
    penalties = [
        ("noise", 0.4 * s.noise_ratio),
        ("boundary", 0.0 if s.boundary_integrity else 0.3),
        ("context", context_penalty),
    ]
    label, value = max(penalties, key=lambda kv: kv[1])
    return label if value > 0 else "none"


def format_terminal_report(scores: list, report_path: str) -> str:
    """Compact colorized per-chunk summary (worst-first) for the terminal."""
    lines = []
    lines.append("")
    lines.append("Readiness report (worst first):")
    for s in _sort_worst_first(scores):
        badge = click.style(f"[{s.grade}]", fg=_GRADE_COLORS[s.grade], bold=True)
        lines.append(f"  {badge} {s.chunk_id}  score {s.score:.2f}  "
                     f"worst penalty: {_dominant_penalty(s)}")
    lines.append(f"  Report: {report_path}")
    return "\n".join(lines)
