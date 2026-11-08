"""Reciprocal Rank Fusion over any number of ranked chunk-id lists.

- 1-based ranks
- score = sum(1 / (k + rank)) across every list
- duplicates within a list are counted once (first occurrence)
- a chunk absent from a list contributes 0 for that list
- ties broken deterministically by chunk_id ascending
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass
class FusedResult:
    chunk_id: str
    score: float
    ranks: dict[str, int] = field(default_factory=dict)


def fuse(
    ranked_lists: Mapping[str, Sequence[str]] | Sequence[Sequence[str]],
    k: int = 60,
) -> list[FusedResult]:
    if isinstance(ranked_lists, Mapping):
        named = [(str(name), list(items)) for name, items in ranked_lists.items()]
    else:
        named = [(f"list_{i}", list(items)) for i, items in enumerate(ranked_lists)]

    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}

    for name, items in named:
        seen: set[str] = set()
        rank = 0
        for chunk_id in items:
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            ranks.setdefault(chunk_id, {})[name] = rank

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [FusedResult(chunk_id=cid, score=score, ranks=ranks.get(cid, {})) for cid, score in ordered]
