"""Machine-derived retrieval gold labels for real stories (REAL_RAG_BUILD.md, Stage 3).

A provision is gold-relevant for a story only if every one of its
machine-verified conditions evaluates TRUE on the story's stated facts
(``case_facts``).  Provisions whose conditions include a ``manual`` one can never
be TRUE, so they are never labelled relevant.  Labels never come from the
retriever or an LLM.

A row with no gold-relevant provision cannot be labelled (absence of a
derivation is not evidence of irrelevance) and is excluded; counts are printed.
Unlabelled provisions are not known to be irrelevant, so precision computed on
these labels is a lower bound.

Usage::

    python -m ai_lawyer.evaluation.derive_labels
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ai_lawyer.contracts.models import ALLOWED_FACT_TYPES, Fact
from ai_lawyer.legal_engine.applicability import evaluate_provision
from ai_lawyer.legal_rag.corpus_loader import Corpus, load_corpus

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
STORIES = DATASET_DIR / "real_stories.jsonl"
OUT = DATASET_DIR / "real_retrieval_labels.jsonl"
GOLD_GRADE = 2  # "relevant" threshold used by the metrics


def facts_from(case_facts: dict[str, Any]) -> list[Fact]:
    return [
        Fact(
            case_id="label-derivation",
            fact_type=fact_type,
            raw_value=str(value),
            normalised_value=value,
            source_type="user_message",
            source_id="story",
            status="user_reported",
        )
        for fact_type, value in case_facts.items()
        if fact_type in ALLOWED_FACT_TYPES
    ]


def derive(story: dict[str, Any], corpus: Corpus) -> dict[str, Any]:
    facts = facts_from(story.get("case_facts", {}))
    relevant: list[str] = []
    trace: dict[str, str] = {}
    for provision_id in sorted(corpus.usable_ids()):
        provision = corpus.get(provision_id)
        if not provision.conditions:
            continue
        result = evaluate_provision(provision, facts)
        trace[provision_id] = result.label
        if result.value is True:
            relevant.append(provision_id)
    return {
        "test_id": story["test_id"],
        "data_origin": story["data_origin"],
        "split": story["split"],
        "category": story.get("category"),
        "user_query": story["turns"][0]["message"],
        "case_facts": story.get("case_facts", {}),
        "as_of_date": story.get("now"),
        "expected_provision_ids": relevant,
        "essential_provision_ids": relevant,
        "relevance_by_provision": {pid: GOLD_GRADE for pid in relevant},
        "applicability_trace": trace,
        "expected_retrieval_status": "provisions_expected" if relevant else "not_derivable",
        "labeling_status": "machine_derived" if relevant else "excluded_not_derivable",
        "annotation_author": "machine (derive_labels; not a human label)",
        "corpus_version": corpus.corpus_version,
    }


def run(stories_path: Path = STORIES, out_path: Path = OUT, corpus: Corpus | None = None) -> list[dict[str, Any]]:
    corpus = corpus or load_corpus("real")
    stories = [json.loads(line) for line in stories_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [derive(story, corpus) for story in stories]
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lawyer.evaluation.derive_labels")
    parser.add_argument("--stories", type=Path, default=STORIES)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    rows = run(args.stories, args.out)
    status = Counter((r["split"], r["labeling_status"]) for r in rows)
    for (split, label), count in sorted(status.items()):
        print(f"{split:12} {label:24} {count}")
    for r in rows:
        print(f"  {r['test_id']} {r['split']:12} {r['expected_provision_ids']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
