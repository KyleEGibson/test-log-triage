"""Regex rules for failure categories + next steps, and the known-issues list."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .cluster import Cluster


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern
    next_step: str


def _rule(category: str, pattern: str, next_step: str) -> Rule:
    return Rule(category, re.compile(pattern, re.IGNORECASE), next_step)


# first match wins, so the specific ones go above the generic assertion rule
RULES = [
    _rule("crash", r"segmentation fault|SIGSEGV|SIGABRT|core dumped|AddressSanitizer|UndefinedBehaviorSanitizer|access violation",
          "Reproduce under the sanitizer build and read the first stack frame in project code."),
    _rule("resource", r"out of memory|MemoryError|no space left|too many open files|disk (is )?full|resource exhausted",
          "Check memory and disk on the runner; look for leaks or unbounded buffers in the test or code under test."),
    _rule("environment", r"no such file|FileNotFoundError|PermissionError|permission denied|ModuleNotFoundError|ImportError|"
                         r"environment variable|not configured|missing config|command not found",
          "Compare the failing runner's setup (files, permissions, installed packages, env vars) with a passing one."),
    _rule("timeout", r"timed? ?out|timeout|deadline exceeded|did not return .* within|not running after|took too long",
          "Check whether the target is slow or stuck; compare durations across runs before raising any timeout."),
    _rule("communication", r"connection (refused|reset|aborted)|unreachable|broken pipe|ECONNRESET|"
                           r"comm(unication)? (error|failure)|no response|socket|unavailable",
          "Check the link and the peer process first (cables, ports, service up); rerun to see if it is intermittent."),
    _rule("data_integrity", r"crc|checksum|mismatch|corrupt|parity|sha-?256|integrity",
          "Capture the raw bytes on both ends and compare; suspect the transport or storage before the logic."),
    _rule("limit_violation", r"outside limits|out of (range|tolerance|spec)|exceeds|above (the )?limit|below (the )?limit",
          "Plot this measurement across recent runs: a trend points at drift (hardware, station, environment), "
          "a step change at a change (lot, firmware, config)."),
    _rule("assertion", r"AssertionError|DID NOT RAISE|assert |expected|Expected equality|Value of:|EXPECT_|ASSERT_|!=|==",
          "Read the assertion and the code under test; check whether the expectation or the behaviour changed recently."),
]
CATEGORIES = [r.category for r in RULES] + ["unknown"]


def classify_text(text: str) -> Rule | None:
    return next((rule for rule in RULES if rule.pattern.search(text)), None)


def classify(cluster: Cluster) -> None:
    text = " ".join([cluster.signature, *cluster.samples(3)])
    rule = classify_text(text)
    cluster.category = rule.category if rule else "unknown"
    cluster.next_step = rule.next_step if rule else "Read a full failing log; no rule matched this message."


def load_known_issues(path: str | Path | None) -> list[dict]:
    # YAML list of {id, title, pattern, status: open|fixed, link?}
    if not path:
        return []
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    for entry in entries:
        missing = {"id", "title", "pattern", "status"} - set(entry)
        if missing:
            raise ValueError(f"known issue {entry.get('id', '?')}: missing {', '.join(sorted(missing))}")
        if entry["status"] not in ("open", "fixed"):
            raise ValueError(f"known issue {entry['id']}: status must be open or fixed")
        entry["regex"] = re.compile(entry["pattern"], re.IGNORECASE)
    return entries


def match_known(cluster: Cluster, issues: list[dict]) -> None:
    # a match on a fixed issue means it came back
    texts = [cluster.signature, *cluster.samples(5)]
    for issue in issues:
        if any(issue["regex"].search(t) for t in texts):
            cluster.known_issue = {k: v for k, v in issue.items() if k != "regex"}
            cluster.regression = issue["status"] == "fixed"
            return
