"""--llm: ask Claude for a likely cause + next step per cluster.

Batched per cluster (not per failure), sends only masked signatures and short
samples (no tracebacks), JSON-schema output, cached by content hash. If
anything goes wrong we keep the rule labels and report the error.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .classify import CATEGORIES
from .cluster import Cluster

MODEL = "claude-opus-5-5"
MAX_SAMPLE_CHARS = 300
MAX_CLUSTERS_PER_REQUEST = 40

SYSTEM = (
    "You are a senior test engineer triaging automated test failures. Each cluster groups failures whose "
    "messages share a signature, where variable values are masked as <NUM>, <IP>, <HEX> and similar. "
    "For every cluster, give the most likely cause as a hypothesis an engineer can check, and the single "
    "most useful next debugging step. Base this only on the messages and test names provided; when they "
    "do not support a specific cause, say what evidence would decide it and set confidence to low."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "likely_cause": {"type": "string"},
                    "next_step": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["id", "category", "likely_cause", "next_step", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


@dataclass
class LlmResult:
    explained: int = 0
    cached: int = 0
    error: str = ""
    request_id: str = ""


def _payload(cluster: Cluster) -> dict:
    return {
        "id": cluster.id,
        "failures": cluster.size,
        "signature": cluster.signature,
        "rule_category": cluster.category,
        "samples": [s[:MAX_SAMPLE_CHARS] for s in cluster.samples(3)],
        "tests": cluster.tests[:10],
    }


def _key(payload: dict) -> str:
    stable = {k: v for k, v in payload.items() if k not in ("id", "failures")}
    return hashlib.sha256((MODEL + json.dumps(stable, sort_keys=True)).encode()).hexdigest()


def explain(clusters: list[Cluster], cache_dir: str | Path = ".triage-cache", client=None) -> LlmResult:
    result = LlmResult()
    cache_file = Path(cache_dir) / "explanations.json"
    cache: dict = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}

    pending = []
    for cluster in clusters:
        payload = _payload(cluster)
        hit = cache.get(_key(payload))
        if hit:
            cluster.explanation = hit
            result.cached += 1
        else:
            pending.append((cluster, payload))

    for start in range(0, len(pending), MAX_CLUSTERS_PER_REQUEST):
        batch = pending[start:start + MAX_CLUSTERS_PER_REQUEST]
        try:
            answers, request_id = _ask([p for _, p in batch], client)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to rules
            result.error = f"{type(exc).__name__}: {exc}"
            break
        result.request_id = request_id
        by_id = {a["id"]: a for a in answers}
        for cluster, payload in batch:
            answer = by_id.get(cluster.id)
            if answer:
                explanation = {k: answer[k] for k in ("category", "likely_cause", "next_step", "confidence")}
                cluster.explanation = explanation
                cache[_key(payload)] = explanation
                result.explained += 1

    if result.explained:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _ask(payloads: list[dict], client=None) -> tuple[list[dict], str]:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY, or an `ant auth login` profile
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if a safety classifier declines, retry on the recommended fallback model
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Triage these failure clusters:\n"
                                              + json.dumps(payloads, indent=1)}],
    )
    request_id = getattr(response, "_request_id", "") or ""
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined the request (request {request_id})")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"response truncated at max_tokens (request {request_id})")
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)["clusters"], request_id
