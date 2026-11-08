"""Verbatim context compression.

Reference technique
-------------------
The reference RAG project scores individual sentences and then *splices the
best ones together* before sending them to the model.  That is acceptable for
research papers; it is not acceptable for statutes.  Removing a proviso from
its main clause can invert the rule:

    "The consumer may return the goods within thirty days provided that the
     goods are unused."

Drop the second half and the sentence says something the law does not say.

Legal-safe technique
--------------------
This module still performs a compression *stage*, but it may only return a
**contiguous slice of the original text**, chosen at sentence boundaries.  It
never reorders, rewrites, merges or paraphrases.  Consequences:

* the returned text is always ``startswith`` of the provision, so it can be
  quoted and checked verbatim;
* if the provision carries provisos or exceptions and they do not fit inside
  the character budget, the text is returned **uncompressed** - a qualifier is
  never dropped to save tokens;
* the corpus keeps the full text, so the citation and phrase guards still
  validate against the complete provision.

Disabled by default (``settings.compression_enabled = False``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_QUALIFIER_START = re.compile(
    r"^\s*(provided(?:\s+further)?\s+that|except|unless|subject\s+to|"
    r"notwithstanding|explanation|exception)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CompressedText:
    text: str
    start: int
    end: int
    changed: bool
    kept_qualifiers: bool
    reason: str


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of sentence spans; never empty for non-empty text."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        end = match.start()
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    if not spans and text.strip():
        spans.append((0, len(text)))
    return spans


def _qualifier_spans(text: str, spans: list[tuple[int, int]]) -> list[int]:
    return [i for i, (a, b) in enumerate(spans) if _QUALIFIER_START.match(text[a:b])]


def compress(text: str, max_chars: int = 1200) -> CompressedText:
    """Return a verbatim prefix of ``text`` that keeps every qualifier.

    A prefix is returned because statutory provisions state the operative rule
    first and qualify it afterwards; keeping the prefix preserves that order.
    """
    if not text:
        return CompressedText("", 0, 0, False, False, "empty")
    if max_chars <= 0 or len(text) <= max_chars:
        return CompressedText(text, 0, len(text), False, False, "within budget")

    spans = _sentence_spans(text)
    qualifiers = _qualifier_spans(text, spans)

    # The prefix must at least contain the first sentence.
    required_end = spans[0][1]

    if qualifiers:
        last_qualifier_end = spans[qualifiers[-1]][1]
        if last_qualifier_end > max_chars:
            # Cannot keep every qualifier inside the budget: do not compress.
            return CompressedText(
                text, 0, len(text), False, True, "qualifiers exceed budget; left intact"
            )
        required_end = last_qualifier_end

    # Extend contiguously, sentence by sentence, while the budget allows.
    end = required_end
    for index, (_a, b) in enumerate(spans):
        if b <= end:
            continue
        if b > max_chars:
            break
        end = b

    if end >= len(text):
        return CompressedText(text, 0, len(text), False, bool(qualifiers), "no trim possible")

    return CompressedText(
        text[:end].rstrip(),
        0,
        end,
        True,
        bool(qualifiers),
        "trimmed at sentence boundary",
    )


def compress_provision(
    *,
    query: str,
    text: str,
    max_chars: int,
) -> CompressedText:
    """Entry point used by the prompt builder.

    ``query`` is accepted for auditability and future scoring; the current
    legal-safe rule is structural rather than relevance-based, because a
    relevance-scored splice is exactly what must not happen to a statute.
    """
    del query  # structural rule only; kept for a stable call signature
    return compress(text, max_chars=max_chars)
