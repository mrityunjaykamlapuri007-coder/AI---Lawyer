"""Unit tests for verbatim context compression.

The property under test is not "does it shorten text" but "can the result ever
say something the provision does not say".  Every assertion below is about
fidelity: verbatim prefix, qualifiers retained, no compression when a
qualifier would be lost.
"""
from __future__ import annotations

from ai_lawyer.legal_rag.compressor import compress, compress_provision

LONG = (
    "The seller shall process every refund within thirty days of the return. "
    "The refund shall be made to the original payment method used by the consumer. "
    "Where the payment was made by cash, the refund may be made by bank transfer. "
    "The seller shall record the date on which the refund was initiated. "
    "The consumer may request an acknowledgement of the refund. "
    "Provided that the goods are unused and the packaging is intact, the consumer "
    "may return the goods within thirty days. "
    "This sub-rule does not apply to perishable goods."
)


def test_short_text_is_returned_unchanged():
    result = compress("A refund must be processed.", max_chars=1200)
    assert result.text == "A refund must be processed."
    assert result.changed is False


def test_result_is_always_a_verbatim_prefix():
    result = compress(LONG, max_chars=500)
    assert LONG.startswith(result.text)
    assert result.changed is True
    assert len(result.text) < len(LONG)


def test_compression_keeps_the_proviso():
    result = compress(LONG, max_chars=520)
    assert "Provided that the goods are unused" in result.text
    assert result.kept_qualifiers is True


def test_no_compression_when_a_qualifier_would_be_dropped():
    # The proviso starts after 500 characters; a 200-character budget cannot
    # keep it, so the text must come back intact rather than truncated.
    result = compress(LONG, max_chars=200)
    assert result.changed is False
    assert result.text == LONG
    assert "budget" in result.reason


def test_no_compression_when_qualifier_is_beyond_any_budget():
    text = "The rule applies to all sellers. " + ("filler sentence. " * 40) + "Except where stated otherwise."
    result = compress(text, max_chars=120)
    assert result.text == text
    assert result.changed is False


def test_text_is_never_rewritten():
    result = compress(LONG, max_chars=400)
    # Same characters, same order, same punctuation, no inserted whitespace.
    assert result.text == LONG[: len(result.text)]
    assert "  " not in result.text


def test_provision_entry_point_accepts_a_query():
    result = compress_provision(query="refund timeline", text=LONG, max_chars=520)
    assert LONG.startswith(result.text)
