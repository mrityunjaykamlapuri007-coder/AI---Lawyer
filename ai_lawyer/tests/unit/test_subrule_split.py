from __future__ import annotations

import json

import pytest

from ai_lawyer.legal_rag.machine_verify import (
    _affected_sub_rules,
    _sub_rule_number,
    substitution_hits,
)
from ai_lawyer.legal_rag.subrule_split import apply_split, make_children, split_text

RULE = (
    "4. Duties of test entities. ---\n"
    "(1) A test entity shall register.\n"
    "(2) Every test entity shall publish a contact.\n"
    "Provided that the contact may be online.\n"
    "(3) No test entity shall charge a cancellation fee.\n"
)
PARENT = {
    "provision_id": "T_P004",
    "source_id": "T",
    "citation": "Test Rules, provision 4",
    "hierarchy_type": "rule",
    "parent_provision_id": None,
    "original_text": RULE,
    "review_status": "rejected",
}


def test_slices_are_contiguous_and_cover_the_parent():
    pieces = split_text(RULE)

    assert [p["sub_rule"] for p in pieces] == [1, 2, 3]
    assert "".join(RULE[p["start"]:p["end"]] for p in pieces) == RULE
    assert pieces[0]["text"].startswith("4. Duties")  # heading stays with (1)
    assert "Provided that" in pieces[1]["text"]  # proviso stays with its sub-rule


def test_gap_in_numbering_refuses_to_split():
    assert split_text("4. X\n(1) a.\n(3) b.\n") == []


def test_children_start_unverified_with_recorded_slice():
    children = make_children(PARENT)

    assert [c["provision_id"] for c in children] == ["T_P004_SR01", "T_P004_SR02", "T_P004_SR03"]
    assert children[1]["citation"] == "Test Rules, provision 4, sub-rule (2)"
    assert all(c["review_status"] == "unverified" for c in children)
    assert all(c["parent_provision_id"] is None for c in children)
    assert children[2]["boundary_adjustment"]["split_from"] == "T_P004"
    for child in children:
        start, end = child["boundary_adjustment"]["slice"]
        assert RULE[start:end].strip() == child["original_text"]


def test_apply_keeps_parent_and_refuses_double_split(tmp_path):
    (tmp_path / "draft_provisions.json").write_text(json.dumps([PARENT]), encoding="utf-8")

    apply_split(tmp_path, "T_P004", apply=True)
    rows = json.loads((tmp_path / "draft_provisions.json").read_text(encoding="utf-8"))

    assert rows[0] == PARENT
    assert len(rows) == 4
    with pytest.raises(ValueError):
        apply_split(tmp_path, "T_P004", apply=True)


def test_amendment_sub_rule_scope_is_parsed():
    text = "in rule 4, for sub-rule (1), the following sub-rule shall be substituted"
    assert _affected_sub_rules(text) == {"4": [1]}
    assert _sub_rule_number("Test Rules, provision 4, sub-rule (10)") == 10


def test_v6_blocks_only_the_substituted_sub_rule_and_the_whole_rule():
    entry = {
        "status": "checked",
        "effect": "substitution",
        "affected_rules": [4],
        "affected_sub_rules": {"4": [1]},
    }
    assert substitution_hits(entry, 4, 1) is True
    assert substitution_hits(entry, 4, None) is True  # whole rule contains (1)
    assert substitution_hits(entry, 4, 2) is False
    assert substitution_hits(entry, 5, None) is False


def test_v6_unknown_scope_inside_rule_blocks_every_sub_rule():
    entry = {"status": "checked", "effect": "substitution", "affected_rules": [4]}
    assert substitution_hits(entry, 4, 2) is True
