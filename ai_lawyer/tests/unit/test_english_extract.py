from __future__ import annotations

from ai_lawyer.legal_rag.english_extract import (
    _candidate_title,
    _counts,
    _line_is_english,
    _metadata,
    _split_parts,
)


def test_counts_treats_devanagari_marks_as_non_latin():
    latin, other = _counts("(क) legal name")

    assert latin == 9
    assert other == 1


def test_section_number_is_kept_on_a_mixed_english_page():
    assert _line_is_english("3.", page_ratio=0.55)
    assert _line_is_english("12.", page_ratio=0.90)


def test_section_number_is_dropped_on_a_hindi_only_page():
    assert not _line_is_english("3.", page_ratio=0.05)
    assert not _line_is_english("(3)", page_ratio=0.55)


def test_roman_numerals_and_boilerplate_are_dropped():
    assert not _line_is_english("II", page_ratio=0.99)
    assert not _line_is_english("THE GAZETTE OF INDIA : EXTRAORDINARY", page_ratio=0.99)
    assert not _line_is_english("[PART II-SEC. 3(i)]", page_ratio=0.99)
    assert not _line_is_english("Uploaded by Dte. of Printing", page_ratio=0.99)


def test_english_lines_are_kept_and_devanagari_lines_are_dropped():
    assert _line_is_english("(a) all goods and services bought or sold", page_ratio=0.5)
    assert not _line_is_english(
        "\u0915\u0947\u0902\u0926\u094d\u0930\u0940\u092f \u0938\u0930\u0915\u093e\u0930", page_ratio=0.5
    )


def test_candidate_title_uses_the_short_title_sentence():
    text = (
        "Short title and commencement.- (1) These rules may be called the "
        "Consumer Protection (E-Commerce) Rules, 2020."
    )
    assert _candidate_title(text) == "Consumer Protection (E-Commerce) Rules, 2020"


def test_candidate_title_falls_back_to_an_all_caps_heading():
    text = "Preamble\nTHE CONSUMER PROTECTION ACT, 2019\n1. Short title."
    assert _candidate_title(text) == "THE CONSUMER PROTECTION ACT, 2019"


def test_candidate_title_returns_none_without_a_heading():
    assert _candidate_title("ordinary prose without a title\n") is None


def test_metadata_extracts_only_quoted_candidates():
    text = (
        "NEW DELHI, WEDNESDAY, JULY 15, 2020/ASHADHA 24, 1942\n"
        "MINISTRY OF CONSUMER AFFAIRS, FOOD AND PUBLIC DISTRIBUTION\n"
        "3146 GI/2020\n"
        "comes into force on the 20th day of July,2020\n"
    )
    metadata = _metadata(text)

    assert metadata["candidate_dates"] == ["JULY 15, 2020"]
    assert metadata["candidate_departments"] == [
        "MINISTRY OF CONSUMER AFFAIRS, FOOD AND PUBLIC DISTRIBUTION"
    ]
    assert metadata["candidate_gazette_ids"] == ["3146 GI/2020"]


def test_split_parts_splits_two_notifications():
    page_lines = [
        (1, ["MINISTRY OF CONSUMER AFFAIRS", "NOTIFICATION", "1. First rule."]),
        (2, ["2. Second rule."]),
        (3, ["NOTIFICATION", "1. Other rule."]),
        (4, ["2. Other second rule."]),
    ]
    parts = _split_parts(page_lines, "sample")

    assert len(parts) == 2
    assert [page for page, _ in parts[0][0]] == [1, 2]
    assert parts[0][1] == "_1"
    assert [page for page, _ in parts[1][0]] == [3, 4]
    assert parts[1][1] == "_2"


def test_split_parts_keeps_a_single_notification_whole():
    page_lines = [
        (7, ["NOTIFICATION", "1. First rule."]),
        (8, ["2. Second rule."]),
    ]
    parts = _split_parts(page_lines, "sample")

    assert len(parts) == 1
    assert [page for page, _ in parts[0][0]] == [7, 8]
    assert parts[0][1] == "_1"
