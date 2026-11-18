"""Run report of an httrack-profile fetch. URLs stored here are already redacted."""

from dataclasses import dataclass, field

from dograpper.utils.redact import neutralize_controls

MAX_SHOWN_ERRORS = 10


@dataclass
class RunReport:
    status_counts: dict[str, int] = field(
        default_factory=lambda: {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "error": 0})
    challenged: list[str] = field(default_factory=list)
    robots_blocked: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    retried: int = 0
    out_of_scope: list[str] = field(default_factory=list)
    errors: list[tuple[str, str, str | None]] = field(default_factory=list)
    partial: bool = False
    not_modified: int = 0  # update mode: 304 to a revalidation
    from_cache: int = 0  # --cache 1: recorded files loaded without a request
    kept: list[tuple[str, str]] = field(default_factory=list)  # update: (URL, error) kept over
    unreached: list[str] = field(default_factory=list)  # previous run's files this one missed


def format_report(r: RunReport, verbose: bool) -> list[str]:
    counts = ", ".join(f"{k}={v}" for k, v in r.status_counts.items())
    lines = [f"Responses: {counts}; retried: {r.retried}"]
    for label, urls in (("Challenged", r.challenged), ("Blocked by robots.txt", r.robots_blocked),
                        ("Out of scope", r.out_of_scope),
                        ("Filtered by --include-extensions", r.filtered)):
        if urls:
            lines.append(f"{label}: {len(urls)}")
            if verbose:
                lines.extend(neutralize_controls(f"  {u}") for u in urls)
    if r.not_modified:
        lines.append(f"Not modified (304): {r.not_modified}")
    if r.from_cache:  # HTTrack -C1's "File immediately loaded from cache" (htsback.c:2529)
        lines.append(f"Loaded from cache without a request: {r.from_cache}")
    if r.kept:  # HTTrack's "Kept existing file ... after error N on update" (htsback.c:4266)
        lines.append(f"Kept the previous copy after an error: {len(r.kept)}")
        if verbose:
            lines.extend(neutralize_controls(f"  {u}: {why}") for u, why in r.kept)
    if r.unreached:  # what HTTrack -X would purge (spec 5.6: never purged)
        lines.append(f"Not reached this run, kept on disk: {len(r.unreached)}")
        if verbose:
            lines.extend(neutralize_controls(f"  {u}") for u in r.unreached)
    if r.errors:
        shown = r.errors if verbose else r.errors[:MAX_SHOWN_ERRORS]
        lines.append(f"Errors: {len(r.errors)}")
        for url, reason, referrer in shown:
            via = f" (from {referrer})" if referrer else ""
            lines.append(neutralize_controls(f"  {url}: {reason}{via}"))
        if len(shown) < len(r.errors):
            lines.append(f"  ... {len(r.errors) - len(shown)} more (use --verbose)")
    if r.partial:
        lines.append("Partial: max-links reached, remaining URLs were not fetched")
    return lines
