from __future__ import annotations

from ai_lawyer.legal_rag.english_extract import (
    _candidate_title,
    _counts,
    _line_is_english,
    _metadata,
    _split_parts,
    text_integrity_flags,
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


# ---------------------------------------------------------------------------
# text-layer number integrity
# ---------------------------------------------------------------------------
def test_integrity_flags_clean_gazette_text_is_empty():
    text = (
        "NEW DELHI, THURSDAY, JULY 23, 2020\n"
        "G.S.R. 462(E).—In exercise of the powers conferred by section 101.\n"
        "No. 358]\n"
        "These rules shall come into force on the 23rd day of July, 2020."
    )
    assert text_integrity_flags(text) == []


def test_integrity_flags_detect_dropped_gsr_number():
    text = "NOTIFICATION\nG.S.R.    (E).—In exercise of the powers conferred by section 101."
    assert "missing_gsr_number" in text_integrity_flags(text)


def test_integrity_flags_detect_a_partially_rendered_gsr_number():
    # Digits are dropped individually, so one G.S.R. number can survive while
    # another is reduced to a single digit.
    text = (
        "G.S.R.    (E).—notification number one.\n"
        "vide number G.S.R. 4   (E), dated the   rd July, 2020."
    )
    assert "missing_gsr_number" in text_integrity_flags(text)


def test_integrity_flags_detect_dropped_gazette_number():
    assert "missing_gazette_number" in text_integrity_flags("No. ]\nNOTIFICATION")


def test_integrity_flags_detect_dropped_commencement_date():
    text = (
        "1. Short title and commencement.\n"
        "They shall come into force with effect from  st January      ."
    )
    flags = text_integrity_flags(text)
    assert "missing_effective_date" in flags
    assert "missing_commencement_date" in flags


def test_integrity_flags_detect_a_text_layer_with_no_digits():
    text = "rule text without any number in it at all " * 30
    assert "no_digits_in_text_layer" in text_integrity_flags(text)
