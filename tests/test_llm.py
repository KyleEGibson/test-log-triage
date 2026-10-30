"""The optional Claude step, against a fake client: no network, no cost.

Checks the request shape (model, structured output schema, fallback opt-in),
what data is sent, caching, batching, and every failure path falling back to
the rule-based labels.
"""

import json
from types import SimpleNamespace

import pytest

from triage import llm
from triage.classify import classify
from triage.cluster import cluster_failures
from triage.parsers import Failure


class FakeMessages:
    def __init__(self, respond):
        self.calls = []
        self.respond = respond

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.respond(kwargs)


def fake_client(respond):
    messages = FakeMessages(respond)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def answer_all(kwargs, **overrides):
    payload = json.loads(kwargs["messages"][0]["content"].split("\n", 1)[1])
    body = {"clusters": [{"id": p["id"], "category": p["rule_category"], "likely_cause": f"cause {p['id']}",
                          "next_step": "check it", "confidence": "medium"} for p in payload]}
    return SimpleNamespace(stop_reason=overrides.get("stop_reason", "end_turn"), _request_id="req_test",
                           content=[SimpleNamespace(type="text", text=overrides.get("text", json.dumps(body)))])


def make_clusters(n=3):
    failures = []
    for i in range(n):
        for run in range(2):
            failures.append(Failure(f"tests/t.py::test_{i}", f"Error kind {chr(65 + i)} at 10.0.0.{run}:80 value {run}.5",
                                    "Traceback (most recent call last):\n  File \"/secret/path/app.py\"\nSECRET-TOKEN-123",
                                    "failure", "r.xml"))
    clusters = cluster_failures(failures)
    for c in clusters:
        classify(c)
    return clusters


def test_request_shape(tmp_path):
    client, messages = fake_client(answer_all)
    llm.explain(make_clusters(), cache_dir=tmp_path, client=client)
    [call] = messages.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in call  # removed in SDK 1.x / rejected by current models


def test_only_masked_summaries_leave_the_machine(tmp_path):
    client, messages = fake_client(answer_all)
    llm.explain(make_clusters(), cache_dir=tmp_path, client=client)
    sent = messages.calls[0]["messages"][0]["content"]
    assert "SECRET-TOKEN-123" not in sent and "/secret/path" not in sent   # tracebacks never sent
    assert "<IP>" in sent and "<NUM>" in sent                             # signatures are masked


def test_explanations_attached_and_cached(tmp_path):
    clusters = make_clusters()
    client, messages = fake_client(answer_all)
    first = llm.explain(clusters, cache_dir=tmp_path, client=client)
    assert first.explained == 3 and first.request_id == "req_test"
    assert clusters[0].explanation["likely_cause"].startswith("cause")

    again = make_clusters()
    second = llm.explain(again, cache_dir=tmp_path, client=client)
    assert second.cached == 3 and second.explained == 0
    assert len(messages.calls) == 1  # no second paid request


def test_large_runs_are_batched(tmp_path):
    client, messages = fake_client(answer_all)
    result = llm.explain(make_clusters(llm.MAX_CLUSTERS_PER_REQUEST + 5), cache_dir=tmp_path, client=client)
    assert len(messages.calls) == 2 and result.explained == llm.MAX_CLUSTERS_PER_REQUEST + 5


@pytest.mark.parametrize("overrides, message", [
    ({"stop_reason": "refusal"}, "declined"),
    ({"stop_reason": "max_tokens"}, "truncated"),
    ({"text": "not json"}, "JSONDecodeError"),
])
def test_failures_fall_back_to_rules(tmp_path, overrides, message):
    clusters = make_clusters()
    labels_before = [(c.category, c.next_step) for c in clusters]
    client, _ = fake_client(lambda kw: answer_all(kw, **overrides))
    result = llm.explain(clusters, cache_dir=tmp_path, client=client)
    assert message in result.error
    assert all(c.explanation is None for c in clusters)
    assert [(c.category, c.next_step) for c in clusters] == labels_before  # rule labels untouched
    assert not (tmp_path / "explanations.json").exists()  # nothing bad cached


def test_api_exception_is_contained(tmp_path):
    def boom(kwargs):
        raise ConnectionError("network down")
    client, _ = fake_client(boom)
    result = llm.explain(make_clusters(), cache_dir=tmp_path, client=client)
    assert result.error == "ConnectionError: network down"


def test_schema_enum_matches_rule_categories():
    from triage.classify import CATEGORIES
    enum = llm.SCHEMA["properties"]["clusters"]["items"]["properties"]["category"]["enum"]
    assert enum == CATEGORIES
