"""triage run results/*.xml [--known known_issues.yaml] [--llm] [--out reports]
triage eval
"""

from __future__ import annotations

import argparse
import sys

from . import evaluate
from .classify import classify, load_known_issues, match_known
from .cluster import cluster_failures
from .parsers import collect
from .report import markdown, write


def cmd_run(args) -> int:
    failures = collect(args.paths)
    if not failures:
        print("no failing tests found")
        return 0
    clusters = cluster_failures(failures, merge_threshold=args.merge_threshold)
    issues = load_known_issues(args.known)
    for c in clusters:
        classify(c)
        match_known(c, issues)

    note = ""
    if args.llm:
        from .llm import MODEL, explain

        result = explain(clusters, cache_dir=args.cache)
        if result.error:
            note = f"AI hypotheses unavailable ({result.error}); rule-based labels shown."
        else:
            note = (f"AI hypotheses from {MODEL} for {result.explained + result.cached} clusters "
                    f"({result.cached} from cache). They are hypotheses to check, not findings.")
    sources = sorted({f.source for f in failures})
    print(markdown(clusters, len(failures), sources, note))
    for path in write(clusters, len(failures), sources, args.out, note):
        print(f"report: {path}")
    regressions = sum(c.regression for c in clusters)
    return 2 if regressions and args.fail_on_regression else 0


def cmd_eval(args) -> int:
    print(evaluate.table(evaluate.sweep(n=args.n, seed=args.seed)))
    return 0


def main(argv: list[str] | None = None) -> int:
    # old Windows code pages crash on some characters in log messages; replace them
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="triage", description="Group failing tests by root cause.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="triage JUnit XML files or directories")
    run.add_argument("paths", nargs="+")
    run.add_argument("--known", help="known issues YAML")
    run.add_argument("--llm", action="store_true", help="add Claude cause hypotheses (sends masked messages to the API)")
    run.add_argument("--merge-threshold", type=float, default=None,
                     help="also merge signatures closer than this cosine distance (off by default, see docs)")
    run.add_argument("--out", default="reports")
    run.add_argument("--cache", default=".triage-cache")
    run.add_argument("--fail-on-regression", action="store_true", help="exit 2 if a fixed issue reappears")
    run.set_defaults(fn=cmd_run)
    ev = sub.add_parser("eval", help="score clustering on the labeled synthetic corpus")
    ev.add_argument("--n", type=int, default=400)
    ev.add_argument("--seed", type=int, default=7)
    ev.set_defaults(fn=cmd_eval)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
