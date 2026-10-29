"""Markdown (for CI summaries) and HTML reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .cluster import Cluster

_env = Environment(loader=PackageLoader("triage", "templates"), autoescape=select_autoescape(["j2"]))


def _status(c: Cluster) -> str:
    if c.regression:
        return f"REGRESSION of {c.known_issue['id']}"
    if c.known_issue:
        return f"known: {c.known_issue['id']}"
    return "NEW"


def markdown(clusters: list[Cluster], total: int, sources: list[str], llm_note: str = "") -> str:
    new = sum(1 for c in clusters if not c.known_issue)
    regressions = sum(c.regression for c in clusters)
    lines = [
        "## Test failure triage",
        "",
        f"**{total} failures, {len(clusters)} distinct problems**: {new} new, {regressions} regressions, "
        f"from {len(sources)} result file(s)",
        "",
        "| # | Failures | Status | Category | Signature | Next step |",
        "|---:|---:|---|---|---|---|",
    ]
    for c in clusters:
        step = c.explanation["next_step"] if c.explanation else c.next_step
        lines.append(f"| {c.id} | {c.size} | {_status(c)} | {c.category} | `{c.signature[:120]}` | {step} |")
    if llm_note:
        lines += ["", f"_{llm_note}_"]
    return "\n".join(lines) + "\n"


def write(clusters: list[Cluster], total: int, sources: list[str], out_dir: str | Path, llm_note: str = "") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / "triage.md"
    md.write_text(markdown(clusters, total, sources, llm_note), encoding="utf-8")
    html = out / "triage.html"
    html.write_text(_env.get_template("report.html.j2").render(
        clusters=clusters, total=total, sources=sources, llm_note=llm_note, status=_status,
        new=sum(1 for c in clusters if not c.known_issue), regressions=sum(c.regression for c in clusters),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"), version=__version__,
        by_id={c.id: c for c in clusters},
    ), encoding="utf-8")
    return [html, md]
