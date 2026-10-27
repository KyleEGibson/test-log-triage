"""Masking: what varies between runs must vanish, what identifies the cause must stay."""

import pytest

from triage.normalize import signature


@pytest.mark.parametrize("raw, expected", [
    ("bus voltage (min of 5) = 24.16 V is outside limits 27 .. 29",
     "bus voltage (min of <NUM>) = <NUM> V is outside limits <NUM> .. <NUM>"),
    ("TimeoutError: GIMB:STAT? did not return IDLE within 10.0 s",
     "TimeoutError: GIMB:STAT? did not return IDLE within <NUM> s"),
    ("No such file: '/home/ci/runner-3/work/calibration_12.json'", "No such file: 'calibration_<NUM>.json'"),
    (r"PermissionError: C:\agents\7\_work\results_20261015T101500.db", "PermissionError: results_<NUM>T<NUM>.db"),
    ("connect to 10.0.0.7:5432 failed", "connect to <IP> failed"),
    ("at 2026-10-15T10:15:00.123Z frame 0xDEADbeef", "at <TS> frame <HEX>"),
    ("run 3f2a7c1e-9b0d-4c55-8a7e-1d2c3b4a5f60 failed", "run <UUID> failed"),
    ("unit SN000123 failed", "unit <ID> failed"),
    ("expected -40.5, got +3e-4", "expected <NUM>, got <NUM>"),
    ("sha256 mismatch in int32 field", "sha256 mismatch in int32 field"),   # digits that name things stay
    ("device sh-03 not ready", "device sh-<NUM> not ready"),
    ("test_space_packet.cpp:57: Failure", "test_space_packet.cpp:<LINE>: Failure"),
    ("commit 9f3c2ab41e7d0c55 broke it", "commit <HASH> broke it"),
    ("  lots   of\n whitespace ", "lots of whitespace"),
])
def test_signature(raw, expected):
    assert signature(raw) == expected


def test_same_cause_different_values_share_a_signature():
    a = signature("slot b checksum mismatch after 2 attempts at 10.0.0.4:9003 (sha 8081fc021c71a85c)")
    b = signature("slot b checksum mismatch after 2 attempts at 10.0.0.9:9004 (sha b03466219cc48ab6)")
    assert a == b


def test_signature_length_is_bounded():
    assert len(signature("x " * 1000)) <= 300
