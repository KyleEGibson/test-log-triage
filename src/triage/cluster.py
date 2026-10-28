"""Group failures by exact signature (see normalize.py).

TF-IDF merging exists (merge_threshold) but is off by default because it
merged different root causes on real data. See docs/clustering.md.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer

from .normalize import signature
from .parsers import Failure

RELATED_DISTANCE = 0.5


@dataclass
class Cluster:
    id: int
    failures: list[Failure]
    signatures: Counter
    category: str = "unknown"
    next_step: str = ""
    known_issue: dict | None = None
    regression: bool = False
    explanation: dict | None = None
    related: list[tuple[int, float]] = field(default_factory=list)  # (cluster id, distance)

    @property
    def signature(self) -> str:
        return self.signatures.most_common(1)[0][0]

    @property
    def size(self) -> int:
        return len(self.failures)

    @property
    def tests(self) -> list[str]:
        return sorted({f.test_id for f in self.failures})

    @property
    def sources(self) -> list[str]:
        return sorted({f.source for f in self.failures})

    def samples(self, n: int = 3) -> list[str]:
        seen: list[str] = []
        for f in self.failures:
            if f.text not in seen:
                seen.append(f.text)
            if len(seen) == n:
                break
        return seen


def _tokens(sig: str) -> list[str]:
    return re.findall(r"<[A-Z]+>|[A-Za-z_][A-Za-z_0-9]*|[^\sA-Za-z_0-9]", sig.lower())


def _vectors(signatures: list[str]) -> np.ndarray:
    vectorizer = TfidfVectorizer(tokenizer=_tokens, token_pattern=None, lowercase=False, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(signatures).toarray()
    matrix[~matrix.any(axis=1)] = 1e-9  # empty signatures would break cosine distance
    return matrix


def cluster_failures(failures: list[Failure], merge_threshold: float | None = None) -> list[Cluster]:
    if not failures:
        return []
    sigs = [signature(f.text) for f in failures]
    unique = sorted(set(sigs))

    if merge_threshold is None or len(unique) == 1:
        labels = {sig: i for i, sig in enumerate(unique)}
    else:
        model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                        distance_threshold=merge_threshold)
        labels = dict(zip(unique, model.fit_predict(_vectors(unique)).tolist()))

    groups: dict[int, list[int]] = {}
    for index, sig in enumerate(sigs):
        groups.setdefault(labels[sig], []).append(index)
    clusters = [Cluster(0, [failures[i] for i in idx], Counter(sigs[i] for i in idx)) for idx in groups.values()]
    clusters.sort(key=lambda c: (-c.size, c.signature))
    for number, c in enumerate(clusters, start=1):
        c.id = number
    _link_related(clusters)
    return clusters


def _link_related(clusters: list[Cluster]) -> None:
    if len(clusters) < 2:
        return
    from sklearn.metrics.pairwise import cosine_distances

    distances = cosine_distances(_vectors([c.signature for c in clusters]))
    for i, c in enumerate(clusters):
        near = [(clusters[j].id, float(distances[i, j])) for j in range(len(clusters))
                if j != i and distances[i, j] < RELATED_DISTANCE]
        c.related = sorted(near, key=lambda pair: pair[1])[:3]


def assignment(clusters: list[Cluster], failures: list[Failure]) -> np.ndarray:
    lookup = {id(f): c.id for c in clusters for f in c.failures}
    return np.array([lookup[id(f)] for f in failures])
