"""triage eval: score clustering/classification against corpus.py."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.metrics import adjusted_rand_score, completeness_score, homogeneity_score

from .classify import classify
from .cluster import assignment, cluster_failures
from .corpus import generate


@dataclass
class Score:
    setting: str
    clusters: int
    true_causes: int
    ari: float            # 1.0 = identical partition to the truth
    homogeneity: float    # 1.0 = no cluster mixes two causes   (merging error)
    completeness: float   # 1.0 = no cause split across clusters (splitting error)
    category_accuracy: float


def score(merge_threshold: float | None, n: int = 400, seed: int = 7) -> Score:
    failures, causes, categories = generate(n, seed)
    clusters = cluster_failures(failures, merge_threshold=merge_threshold)
    for c in clusters:
        classify(c)
    predicted = assignment(clusters, failures)
    category_of = {id(f): c.category for c in clusters for f in c.failures}
    correct = sum(category_of[id(f)] == truth for f, truth in zip(failures, categories))
    return Score(
        setting="exact signatures" if merge_threshold is None else f"merge < {merge_threshold:.2f}",
        clusters=len(clusters),
        true_causes=len(set(causes)),
        ari=adjusted_rand_score(causes, predicted),
        homogeneity=homogeneity_score(causes, predicted),
        completeness=completeness_score(causes, predicted),
        category_accuracy=correct / len(failures),
    )


def sweep(thresholds=(None, 0.2, 0.3, 0.4, 0.5, 0.6), **kw) -> list[Score]:
    return [score(t, **kw) for t in thresholds]


def table(scores: list[Score]) -> str:
    lines = ["| Setting | Clusters (true) | ARI | Homogeneity | Completeness | Category accuracy |",
             "|---|---:|---:|---:|---:|---:|"]
    for s in scores:
        lines.append(f"| {s.setting} | {s.clusters} ({s.true_causes}) | {s.ari:.3f} | {s.homogeneity:.3f} "
                     f"| {s.completeness:.3f} | {s.category_accuracy:.1%} |")
    return "\n".join(lines)
