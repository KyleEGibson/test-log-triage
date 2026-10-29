"""Parsing, clustering, classification, known issues and the report, on real and synthetic data."""

from pathlib import Path

import pytest

from triage import evaluate
from triage.classify import CATEGORIES, classify, classify_text, load_known_issues, match_known
from triage.cli import main
from triage.cluster import cluster_failures
from triage.corpus import CAUSES, generate
from triage.parsers import Failure, collect, parse_junit

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

GTEST_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="SpacePacket" tests="2" failures="1">
  <testcase name="RoundTrip" classname="SpacePacket">
    <failure message="test_space_packet.cpp:57&#10;Expected equality of these values:&#10;  decoded.apid" type=""/>
  </testcase>
  <testcase name="BitLayout" classname="SpacePacket"/>
</testsuite></testsuites>"""

PYTEST_ERROR = """<?xml version="1.0"?><testsuites><testsuite name="pytest">
  <testcase classname="tests.test_io" name="test_load">
    <error message="">Traceback (most recent call last):
  File "/home/ci/x.py", line 3
E   FileNotFoundError: [Errno 2] No such file or directory: '/data/cal_7.json'</error>
  </testcase></testsuite></testsuites>"""


def test_real_pytest_junit_samples():
    failures = collect([SAMPLES / "eos-station"])
    assert len(failures) == 25
    assert {f.source for f in failures} == {"run-comm-drop.xml", "run-dead-pixels.xml", "run-gimbal-stall.xml",
                                            "run-temp-drift.xml", "run-volt-sag.xml"}
    assert all("::" in f.test_id and f.message for f in failures)


def test_gtest_junit_uses_first_line_of_message(tmp_path):
    path = tmp_path / "gtest.xml"
    path.write_text(GTEST_JUNIT)
    [failure] = parse_junit(path)
    assert failure.test_id == "SpacePacket::RoundTrip"
    assert failure.text == "test_space_packet.cpp:57"


def test_error_without_message_falls_back_to_marked_line(tmp_path):
    path = tmp_path / "e.xml"
    path.write_text(PYTEST_ERROR)
    [failure] = parse_junit(path)
    assert failure.kind == "error"
    assert failure.text.startswith("FileNotFoundError")


def test_bad_xml_is_reported_with_file_name(tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<testsuite><testcase>")
    with pytest.raises(ValueError, match="broken.xml: not valid JUnit XML"):
        parse_junit(path)


def test_real_samples_cluster_into_distinct_causes():
    clusters = cluster_failures(collect([SAMPLES / "eos-station"]))
    assert len(clusters) == 9
    assert clusters[0].size == 12 and "GIMB:STAT?" in clusters[0].signature
    assert all(len(c.signatures) == 1 for c in clusters)  # exact: one signature per cluster


def test_near_misses_stay_separate_but_are_marked_related():
    """Regression: the first version merged BIT, temperature and voltage limit failures into one cluster."""
    clusters = cluster_failures(collect([SAMPLES / "eos-station"]))
    by_sig = {c.signature.split(" = ")[0]: c for c in clusters}
    bit = by_sig["AssertionError: BIT result"]
    temp = by_sig["AssertionError: maximum temperature"]
    assert bit is not temp
    assert temp.id in [rid for rid, _ in bit.related]


def test_fuzzy_merge_is_opt_in():
    failures = collect([SAMPLES / "eos-station"])
    assert len(cluster_failures(failures, merge_threshold=0.5)) < len(cluster_failures(failures))


def test_corpus_scores_and_why_merging_is_off():
    exact = evaluate.score(None)
    merged = evaluate.score(0.5)
    assert exact.ari == pytest.approx(1.0) and exact.clusters == len(CAUSES)
    assert merged.homogeneity < exact.homogeneity     # merging mixes different causes
    assert merged.completeness == pytest.approx(1.0)  # ...without fixing any split


def test_empty_input():
    assert cluster_failures([]) == []


@pytest.mark.parametrize("text, category", [
    ("Fatal Python error: Segmentation fault", "crash"),
    ("==1==ERROR: AddressSanitizer: heap-buffer-overflow", "crash"),
    ("MemoryError: Unable to allocate 3 GiB", "resource"),
    ("PermissionError: [Errno 13] Permission denied: 'x.db'", "environment"),
    ("TimeoutError: did not return IDLE within 10 s", "timeout"),
    ("ConnectionRefusedError: [Errno 111] Connection refused", "communication"),
    ("CRC mismatch on frame 7", "data_integrity"),
    ("bus voltage = 24.2 V is outside limits 27 .. 29", "limit_violation"),
    ("AssertionError: assert 3 == 4", "assertion"),
    ("Failed: DID NOT RAISE DeviceError", "assertion"),
])
def test_rules(text, category):
    assert classify_text(text).category == category


def test_every_corpus_cause_gets_its_true_category():
    failures, causes, categories = generate(200)
    truth = {id(f): category for f, category in zip(failures, categories)}
    for c in cluster_failures(failures):
        classify(c)
        assert c.category in CATEGORIES
        assert {truth[id(f)] for f in c.failures} == {c.category}, c.signature


def test_unmatched_message_is_unknown():
    c = cluster_failures([Failure("t::x", "the frobnicator wobbled", "", "failure", "a.xml")])[0]
    classify(c)
    assert c.category == "unknown"


def test_known_issues_and_regressions():
    clusters = cluster_failures(collect([SAMPLES / "eos-station"]))
    issues = load_known_issues(SAMPLES / "known_issues.yaml")
    for c in clusters:
        match_known(c, issues)
    regressions = [c for c in clusters if c.regression]
    assert [c.known_issue["id"] for c in regressions] == ["DEF-0017"]
    assert clusters[0].known_issue["id"] == "DEF-0041" and not clusters[0].regression


def test_known_issue_registry_validation(tmp_path):
    bad = tmp_path / "k.yaml"
    bad.write_text("- {id: X-1, title: t, pattern: x, status: wontfix}\n")
    with pytest.raises(ValueError, match="status must be open or fixed"):
        load_known_issues(bad)
    bad.write_text("- {id: X-1, pattern: x}\n")
    with pytest.raises(ValueError, match="missing status, title"):
        load_known_issues(bad)


def test_cli_report_and_regression_gate(tmp_path, capsys):
    args = ["run", str(SAMPLES / "eos-station"), "--known", str(SAMPLES / "known_issues.yaml"), "--out", str(tmp_path)]
    assert main(args) == 0
    assert main(args + ["--fail-on-regression"]) == 2
    out = capsys.readouterr().out
    assert "25 failures" in out and "9 distinct problems" in out and "REGRESSION of DEF-0017" in out
    html = (tmp_path / "triage.html").read_text(encoding="utf-8")
    assert html.count('class="cluster"') == 9 and "Possibly related" in html


def test_cli_eval(capsys):
    assert main(["eval", "--n", "150"]) == 0
    assert "| exact signatures |" in capsys.readouterr().out
