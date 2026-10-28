"""Fake failures with known causes, so `triage eval` has ground truth.

Includes varying hosts/paths/IDs (should still group) and look-alike pairs
like bus voltage vs detector temp limits (should stay apart).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from .parsers import Failure


@dataclass(frozen=True)
class Cause:
    name: str
    category: str
    test: str
    make: callable


def _path(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return f"/home/ci/runner-{rng.randrange(1, 40)}/work/{rng.choice(['app', 'svc', 'station'])}"
    return f"C:\\agents\\{rng.randrange(1, 9)}\\_work\\{rng.randrange(100, 999)}"


def _ts(rng: random.Random) -> str:
    return f"2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}T{rng.randrange(24):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}Z"


CAUSES = [
    Cause("db_refused", "communication", "tests/api/test_orders.py::test_create",
          lambda r: f"ConnectionRefusedError: [Errno 111] Connection refused: {r.randrange(10, 250)}.{r.randrange(256)}.0.{r.randrange(1, 250)}:{r.choice([5432, 5433])}"),
    Cause("api_timeout", "timeout", "tests/api/test_reports.py::test_monthly",
          lambda r: f"TimeoutError: request to 10.1.{r.randrange(256)}.{r.randrange(256)}:8000/api/reports timed out after {r.uniform(5, 30):.1f} s"),
    Cause("frame_crc", "data_integrity", "tests/link/test_downlink.py::test_frames",
          lambda r: f"AssertionError: CRC mismatch on frame {r.randrange(1, 9000)}: expected 0x{r.randrange(65536):04X}, got 0x{r.randrange(65536):04X}"),
    Cause("upload_checksum", "data_integrity", "tests/fleet/test_load.py::test_rollout",
          lambda r: f"transfer: slot b checksum mismatch after 2 attempts; running image untouched (sha256 {uuid.UUID(int=r.getrandbits(128)).hex})"),
    Cause("bus_voltage", "limit_violation", "tests/component/test_power.py::test_bus_voltage",
          lambda r: f"AssertionError: bus voltage = {r.uniform(24, 26.9):.2f} V is outside limits 27 .. 29"),
    Cause("detector_temp", "limit_violation", "tests/component/test_thermal.py::test_temperature_stability",
          lambda r: f"AssertionError: detector temperature = {r.uniform(-38.9, -36):.2f} C is outside limits -41 .. -39"),
    Cause("missing_calibration", "environment", "tests/imager/test_calibrate.py::test_load",
          lambda r: f"FileNotFoundError: [Errno 2] No such file or directory: '{_path(r)}/calibration_{r.randrange(1, 99)}.json'"),
    Cause("results_permission", "environment", "tests/station/test_results.py::test_write",
          lambda r: f"PermissionError: [Errno 13] Permission denied: '{_path(r)}/results_{r.randrange(20260101, 20261231)}.db'"),
    Cause("segfault", "crash", "tests/native/test_codec.py::test_decode",
          lambda r: f"Fatal Python error: Segmentation fault in worker {r.randrange(1, 16)} at 0x{r.getrandbits(48):012x}"),
    Cause("oom", "resource", "tests/imager/test_stack.py::test_large_stack",
          lambda r: f"MemoryError: Unable to allocate {r.randrange(200, 4000)} MiB for an array with shape ({r.randrange(100, 900)}, 640, 512)"),
    Cause("status_assert", "assertion", "tests/system/test_startup.py::test_ready",
          lambda r: f"AssertionError: expected status 'READY' but got 'BOOTING' for run {uuid.UUID(int=r.getrandbits(128))}"),
    Cause("gtest_apid", "assertion", "SpacePacket.RoundTrip",
          lambda r: f"test_space_packet.cpp:{r.randrange(30, 90)}: Expected equality of these values: decoded.apid Which is: {r.randrange(2048)}"),
    Cause("gimbal_settle", "timeout", "tests/component/test_gimbal.py::test_pointing_accuracy",
          lambda r: f"TimeoutError: GIMB:STAT? did not return IDLE within {r.choice([5.0, 10.0])} s (since {_ts(r)})"),
]


def generate(n: int = 400, seed: int = 7) -> tuple[list[Failure], list[str], list[str]]:
    # returns (failures, true cause, true category)
    rng = random.Random(seed)
    weights = [rng.uniform(0.5, 3) for _ in CAUSES]  # uneven, like real failure mixes
    failures, causes, categories = [], [], []
    for i in range(n):
        cause = rng.choices(CAUSES, weights=weights)[0]
        failures.append(Failure(f"{cause.test}[{i % 7}]", cause.make(rng), "", "failure", f"build-{1000 + i // 40}.xml"))
        causes.append(cause.name)
        categories.append(cause.category)
    return failures, causes, categories
