"""Run report of an httrack-profile fetch. URLs stored here are already redacted."""

import re
from dataclasses import dataclass, field

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


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _printable(text: str) -> str:
    return _CONTROL.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def format_report(r: RunReport, verbose: bool) -> list[str]:
    counts = ", ".join(f"{k}={v}" for k, v in r.status_counts.items())
    lines = [f"Responses: {counts}; retried: {r.retried}"]
    for label, urls in (("Challenged", r.challenged), ("Blocked by robots.txt", r.robots_blocked),
                        ("Out of scope", r.out_of_scope),
                        ("Filtered by --include-extensions", r.filtered)):
        if urls:
            lines.append(f"{label}: {len(urls)}")
            if verbose:
                lines.extend(_printable(f"  {u}") for u in urls)
    if r.errors:
        shown = r.errors if verbose else r.errors[:MAX_SHOWN_ERRORS]
        lines.append(f"Errors: {len(r.errors)}")
        for url, reason, referrer in shown:
            via = f" (from {referrer})" if referrer else ""
            lines.append(_printable(f"  {url}: {reason}{via}"))
        if len(shown) < len(r.errors):
            lines.append(f"  ... {len(r.errors) - len(shown)} more (use --verbose)")
    if r.partial:
        lines.append("Partial: max-links reached, remaining URLs were not fetched")
    return lines
