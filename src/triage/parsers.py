"""Read test failures from JUnit XML (pytest, GoogleTest/CTest, Maven Surefire, JMeter...)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Failure:
    test_id: str      # classname::name
    message: str      # the one-line failure message
    details: str      # traceback / body text
    kind: str         # "failure" (assertion) or "error" (crash, setup problem)
    source: str       # which results file it came from

    @property
    def text(self) -> str:
        return self.message or _last_meaningful_line(self.details)


def _last_meaningful_line(details: str) -> str:
    lines = [line.strip() for line in details.splitlines() if line.strip()]
    # pytest marks the failing assertion with "E   "
    marked = [line[1:].strip() for line in lines if line.startswith("E ")]
    if marked:
        return marked[-1]
    return lines[-1] if lines else ""


def parse_junit(path: str | Path) -> list[Failure]:
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path}: not valid JUnit XML ({exc})") from None
    failures = []
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        for kind in ("failure", "error"):
            for node in case.findall(kind):
                message = (node.get("message") or "").strip()
                first_line = message.splitlines()[0].strip() if message else ""
                failures.append(Failure(test_id, first_line, (node.text or "").strip(), kind, path.name))
    return failures


def collect(paths: list[str | Path]) -> list[Failure]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(p.rglob("*.xml")))
        elif p.exists():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return [f for file in files for f in parse_junit(file)]
