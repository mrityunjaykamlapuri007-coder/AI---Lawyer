"""Deterministic fakes used by tests, fixture-mode demos and the evaluation harness.

None of these load a model or touch the network.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Callable, Sequence

import numpy as np
from pydantic import BaseModel

from .errors import ModelOutputInvalid
from .models import Candidate, Evidence, Fact, LegalDraft, PageExtraction

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "is", "are",
    "was", "were", "be", "been", "it", "this", "that", "with", "by", "from", "as",
    "my", "me", "i", "you", "your", "we", "our", "they", "their", "has", "have",
    "had", "not", "no", "but", "if", "about", "what", "should", "can", "could",
}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP]


class HashEmbedder:
    """Deterministic bag-of-hashed-features embedder (L2 normalised).

    Intended for tests and offline fixture mode.  It is not a semantic model;
    it is a measurable lexical baseline that behaves identically every run.
    """

    model_id = "hash-embedder-v1"

    def __init__(self, dimension: int = 512) -> None:
        self.dimension = dimension

    def _vector(self, text: str) -> np.ndarray:
        toks = tokens(text)
        pairs = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        vec = np.zeros(self.dimension, dtype="float32")
        counts = Counter(pairs)
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            idx = raw % self.dimension
            sign = 1.0 if (raw >> 63) & 1 == 0 else -1.0
            vec[idx] += sign * (1.0 + math.log(count))
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        return np.vstack([self._vector(t) for t in texts]).astype("float32")


class IdentityReranker:
    """No-op reranker used when RERANKER_ENABLED=false or in tests."""

    model_id = "identity"

    def rerank(self, query: str, candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, cand in enumerate(candidates):
            item = dict(cand)
            item["rerank_score"] = 1.0 / (i + 1)
            item["original_rank"] = i + 1
            item["new_rank"] = i + 1
            out.append(item)
        return out


class FakeLLM:
    """Scripted / heuristic LLM.

    ``scripts`` maps a task label to a queue of payloads.  A payload can be a
    dict (validated against the requested schema), a model instance, the string
    ``__INVALID_JSON__`` (raises ModelOutputInvalid), or an exception instance.
    """

    provider = "fake"

    def __init__(
        self,
        scripts: dict[str, list[Any]] | None = None,
        *,
        invented_provision_id: str | None = None,
        handlers: dict[str, Callable[[str, dict[str, Any]], Any]] | None = None,
    ) -> None:
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.invented_provision_id = invented_provision_id
        self.handlers = handlers or {}
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, prompt: str, schema: type[BaseModel], options=None):
        opts = dict(options or {})
        task = str(opts.get("task", "default"))
        self.calls.append({"task": task, "options": opts, "prompt": prompt})
        queue = self.scripts.get(task)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            if item == "__INVALID_JSON__":
                raise ModelOutputInvalid("fake invalid JSON")
            if isinstance(item, BaseModel):
                return item  # type: ignore[return-value]
            return schema.model_validate(item)
        if task in self.handlers:
            return schema.model_validate(self.handlers[task](prompt, opts))
        return schema.model_validate(self._default_payload(task, opts, schema))

    def generate_text(self, prompt: str, options=None) -> str:
        return ""

    def health_check(self) -> dict[str, Any]:
        return {"provider": "fake", "ok": True, "model": "deterministic-fake"}

    # -- default deterministic behaviour -----------------------------------
    def _default_payload(self, task: str, opts: dict[str, Any], schema: type[BaseModel]):
        if task == "scope_classifier":
            return {"in_scope": True, "domain": "consumer_refund", "reason": "fake default"}
        if task == "fact_extractor":
            return {"facts": []}
        if task == "relevance_grader":
            return {"grades": self._grade_candidates(opts)}
        if task == "reasoning":
            return self._draft(opts)
        if schema is LegalDraft:
            return self._draft(opts)
        return {}

    def _grade_candidates(self, opts: dict[str, Any]) -> list[dict[str, Any]]:
        def fold(token: str) -> str:
            for suffix in ("ing", "ed", "es", "s"):
                if len(token) > 4 and token.endswith(suffix):
                    return token[: -len(suffix)]
            return token

        case_text = str(opts.get("case_summary", ""))
        q = {fold(t) for t in tokens(case_text)} or {"refund"}
        grades: list[dict[str, Any]] = []
        for cand in opts.get("candidates", []):
            # Coverage of the provision's own text, not of the long case
            # message: otherwise one short relevant provision is always
            # diluted below the acceptance grade.
            provision_text = str(cand.get("original_text", ""))
            p = {fold(t) for t in tokens(provision_text)}
            common = sorted(q & p)
            coverage = len(common) / max(1, len(p))
            if coverage >= 0.28 or len(common) >= 5:
                grade = 3
            elif (coverage >= 0.10 and len(common) >= 2) or coverage >= 0.20:
                grade = 2
            elif coverage >= 0.04 or len(common) >= 1:
                grade = 1
            else:
                grade = 0
            reason = (
                f"Shares case terms {common[:6]}; provision says: {provision_text[:90].strip()!r}."
                if common
                else f"No meaningful overlap with the case; provision says: {provision_text[:90].strip()!r}."
            )
            grades.append({"provision_id": cand["provision_id"], "grade": grade, "reason": reason})
        return grades

    def _draft(self, opts: dict[str, Any]) -> dict[str, Any]:
        accepted = list(opts.get("accepted_provision_ids", []))
        if self.invented_provision_id:
            accepted_out = [self.invented_provision_id]
            analysis = [
                {
                    "provision_id": self.invented_provision_id,
                    "conditional_statement": "This invented provision may apply if the facts are met.",
                    "supporting_fact_ids": [],
                }
            ]
        else:
            accepted_out = accepted
            analysis = [
                {
                    "provision_id": pid,
                    "conditional_statement": "This provision may apply if the facts described are established.",
                    "supporting_fact_ids": [],
                }
                for pid in accepted
            ]
        facts = opts.get("facts", [])
        return {
            "issue_summary": "A consumer says an e-commerce refund is outstanding.",
            "user_reported_facts": [f"{f['fact_type']}: {f['raw_value']}" for f in facts if f.get("status") == "user_reported"],
            "document_supported_facts": [f"{f['fact_type']}: {f['raw_value']}" for f in facts if f.get("status") == "document_supported"],
            "missing_facts": list(opts.get("missing_facts", [])),
            "relevant_provision_ids": accepted_out,
            "application_analysis": analysis,
            "assumptions": [],
            "uncertainties": [],
            "possible_options": [],
            "proposed_outcome": "needs_more_information",
            "proposed_next_step": "Review the structured assessment.",
            "lawyer_needed": {"value": False, "reason": None},
        }


class FakeOCR:
    name = "fake-ocr"

    def __init__(self, text: str = "FAKE OCR TEXT: refund initiated 2 November 2026.") -> None:
        self.text = text

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        return {"text": self.text, "confidence": 0.9, "method": "ocr"}


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.facts: list[Fact] = []
        self.events: list[dict[str, Any]] = []

    def create_case(self, user_id: str, summary: dict[str, Any]) -> str:
        from .ids import new_id

        case_id = new_id("case_")
        self.cases[case_id] = {"user_id": user_id, "summary": summary}
        return case_id

    def add_fact(self, fact: Fact) -> str:
        self.facts.append(fact)
        return fact.fact_id

    def append_event(self, case_id: str, event_type: str, payload: dict[str, Any]) -> int:
        seq = sum(1 for e in self.events if e["case_id"] == case_id) + 1
        self.events.append(
            {"case_id": case_id, "sequence_no": seq, "event_type": event_type, "payload": payload}
        )
        return seq


class FakeJevClient:
    """Offline placeholder.  No endpoint, schema or auth is guessed."""

    def __init__(self, enabled: bool = False, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail

    def is_enabled(self) -> bool:
        return self.enabled

    def advise(self, minimised_state: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "advisory": None}
        if self.fail:
            return {"status": "error", "advisory": None}
        return {"status": "ok", "advisory": None}
