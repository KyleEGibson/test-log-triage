"""Mask the parts of a failure message that change between runs.

    "bus voltage (min of 5) = 24.16 V is outside limits 27 .. 29"
 -> "bus voltage (min of <NUM>) = <NUM> V is outside limits <NUM> .. <NUM>"
"""

from __future__ import annotations

import re

# order matters: specific shapes first, plain numbers last
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "<TS>"),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<TIME>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\blocalhost:\d+\b"), "localhost:<PORT>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{12,}\b"), "<HASH>"),
    # paths: keep the file name (it locates the code), drop directories and line numbers
    (re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.\- ]+)+[\\/]([\w.\-]+\.\w+)"), r"\1"),
    (re.compile(r"(\.\w+):\d+(?::\d+)?\b"), r"\1:<LINE>"),
    (re.compile(r"\b(?:SN|sn|unit|run|job|id|ID)[-_#]?\d+\b"), "<ID>"),
    # long digit runs inside identifiers are dates or counters: results_20261015T1015.db
    (re.compile(r"(?<=[A-Za-z_])\d{4,}"), "<NUM>"),
    # numbers, including ones after "_" or "-" in names (calibration_12, sh-03), but not
    # short digits that are part of a word (sha256, int32, utf8)
    (re.compile(r"(?<![<A-Za-z\d.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\d>])"), "<NUM>"),
    (re.compile(r"\s+"), " "),
]

MAX_LENGTH = 300


def signature(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    text = text.strip()
    return text[:MAX_LENGTH]
