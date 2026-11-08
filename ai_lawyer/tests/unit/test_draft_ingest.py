from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from ai_lawyer.legal_rag.corpus_loader import validate_and_build
from ai_lawyer.legal_rag.draft_ingest import (
    DocumentSpec,
    _provision_flags,
    _section_gaps,
    build_drafts,
    extract_title,
    script_mix_note,
    specs_from_manifest,
    split_sections,
    text_quality,
)
from ai_lawyer.contracts.models import Provision

ACT_TEXT = """===== PAGE 1 =====
THE TEST ACT, 2020
Preamble line that is not a section.

1. First section text.
continues on the next line.

===== PAGE 2 =====
2. Second section text.

3. Third section text.
"""


def test_extract_title_from_uppercase_heading():
    assert extract_title(ACT_TEXT) == "THE TEST ACT, 2020"


def test_extract_title_returns_none_when_absent():
    assert extract_title("lowercase prose only\nno document heading here") is None


def test_split_sections_tracks_pages_and_removes_markers():
    sections = split_sections(ACT_TEXT)

    assert [section.number for section in sections] == [1, 2, 3]
    assert sections[0].text.startswith("1. First section text.")
    assert "PAGE 1" not in sections[0].text
    assert "PAGE 2" not in sections[1].text
    assert sections[0].page_start == 1
    assert sections[0].page_end == 1
    assert sections[1].page_start == 2
    assert sections[2].page_end == 2


def test_split_sections_is_verbatim_except_markers_and_outer_whitespace():
    text = "===== PAGE 1 =====\n1. A.  two spaces\n2. B.\n3. C.\n"
    sections = split_sections(text)

    assert sections[0].text == "1. A.  two spaces"
    assert sections[1].text == "2. B."


def test_split_sections_rejects_non_sequential_numbers():
    text = "1. A\n2. B\n9. Not a heading\n3. C\n"
    sections = split_sections(text)

    assert [section.number for section in sections] == [1, 2, 3]


def test_split_sections_accepts_a_small_gap():
    text = "1. A\n2. B\n4. D\n5. E\n"
    sections = split_sections(text)

    assert [section.number for section in sections] == [1, 2, 4, 5]


def test_split_sections_rejects_out_of_order_number():
    text = "1. A\n2. B\n8. C\n7. D\n5. E\n6. F\n"
    sections = split_sections(text)

    assert [section.number for section in sections] == [1, 2, 5, 6]


def test_split_sections_falls_back_to_whole_document():
    text = "===== PAGE 2 =====\nOnly one section.\n\nNo numbering here.\n"
    sections = split_sections(text)

    assert len(sections) == 1
    assert sections[0].number is None
    assert sections[0].page_start == 2
    assert sections[0].text == "Only one section.\n\nNo numbering here."


def test_text_quality_flags_clean_english_as_low_risk():
    ascii_ratio, letter_ratio, latin_share, risk = text_quality(
        "A clean English sentence with enough letters to pass the threshold.\n"
    )

    assert ascii_ratio > 0.99
    assert letter_ratio > 0.55
    assert latin_share == 1.0
    assert risk == "low"
    assert script_mix_note(latin_share) is None


def test_text_quality_flags_mixed_script_as_high_risk():
    text = "1. Hello world this is an English sentence. " + "\u0915\u0916\u0917\u0918\u0919" * 10
    ascii_ratio, letter_ratio, latin_share, risk = text_quality(text)

    assert risk == "high"
    assert 0.0 < latin_share < 1.0
    assert script_mix_note(latin_share) is not None


def test_text_quality_counts_combining_devanagari_marks():
    text = "(क) legal name of the e-commerce entity;\n"
    _, _, latin_share, risk = text_quality(text)

    assert latin_share < 1.0
    assert risk == "low"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _spec(filename: str, source_id: str = "TEST_ACT") -> DocumentSpec:
    return DocumentSpec(filename, source_id, "act", "section")


def test_build_drafts_writes_unverified_schema_valid_output(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write(corpus_dir / "test_act.txt", ACT_TEXT)

    build = build_drafts(
        corpus_dir,
        specs=[_spec("test_act.txt")],
        retrieved_at=date(2026, 1, 1),
    )

    assert len(build.sources) == 1
    assert len(build.provisions) == 3
    source = build.sources[0]
    assert source.review_status == "unverified"
    assert source.official_url == ""
    assert source.publisher == ""
    assert source.published_date is None
    assert source.effective_from is None
    assert source.version_status == "uncertain"
    assert source.title == "THE TEST ACT, 2020"
    assert [p.provision_id for p in build.provisions] == [
        "TEST_ACT_P001",
        "TEST_ACT_P002",
        "TEST_ACT_P003",
    ]
    assert build.provisions[0].original_text == "1. First section text.\ncontinues on the next line."

    sources = json.loads((build.out_dir / "draft_sources.json").read_text(encoding="utf-8"))
    provisions = json.loads(
        (build.out_dir / "draft_provisions.json").read_text(encoding="utf-8")
    )
    corpus = validate_and_build(sources, provisions, directory=None, warn_unusable=False)
    assert corpus.usable_count == 0
    assert corpus.unusable_count == len(provisions)


def test_build_drafts_never_writes_real_corpus_files(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write(corpus_dir / "test_act.txt", ACT_TEXT)

    build = build_drafts(corpus_dir, specs=[_spec("test_act.txt")])

    for directory in (corpus_dir, build.out_dir):
        assert not (directory / "sources.json").exists()
        assert not (directory / "provisions.json").exists()
    assert (build.out_dir / "draft_sources.json").exists()
    assert (build.out_dir / "draft_provisions.json").exists()


def test_build_drafts_writes_review_worksheets_and_manifest(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write(corpus_dir / "test_act.txt", ACT_TEXT)

    build = build_drafts(corpus_dir, specs=[_spec("test_act.txt")])

    with (build.out_dir / "provisions_review.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["provision_id"] == "TEST_ACT_P001"
    assert rows[0]["decision"] == ""
    assert rows[0]["text_preview"].startswith("1. First section text.")

    with (build.out_dir / "sources_review.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        source_rows = list(csv.DictReader(handle))
    assert len(source_rows) == 1
    assert source_rows[0]["review_status"] == "unverified"
    assert source_rows[0]["official_url"] == ""

    manifest = json.loads(
        (build.out_dir / "draft_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["draft_only"] is True
    assert manifest["citation_ready"] is False
    assert manifest["provisions_count"] == 3
    assert (build.out_dir / "DRAFT_REVIEW.md").exists()
    checklist = (build.out_dir / "REVIEWER_CHECKLIST.md").read_text(encoding="utf-8")
    assert "NOT been reviewed" in checklist
    assert "TEST_ACT_P001" in checklist
    assert "Must be supplied by a human" in checklist
    assert "official URL" in checklist


def test_build_drafts_refuses_to_overwrite_verified_draft(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write(corpus_dir / "test_act.txt", ACT_TEXT)
    out_dir = corpus_dir / "draft"
    out_dir.mkdir()
    _write(
        out_dir / "draft_sources.json",
        json.dumps([{"source_id": "TEST_ACT", "review_status": "human_verified"}]),
    )

    with pytest.raises(FileExistsError):
        build_drafts(corpus_dir, out_dir, specs=[_spec("test_act.txt")])

    build = build_drafts(
        corpus_dir, out_dir, specs=[_spec("test_act.txt")], force=True
    )
    assert build.sources[0].review_status == "unverified"


def test_build_drafts_errors_when_no_known_file_exists(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        build_drafts(corpus_dir, specs=[_spec("missing.txt")])


def test_split_sections_accepts_two_sections_by_default():
    assert [section.number for section in split_sections("1. A\n2. B\n")] == [1, 2]


def test_specs_from_manifest_reads_candidates(tmp_path: Path):
    manifest = tmp_path / "metadata.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": "part_1.txt",
                        "source_id": "PART_1",
                        "source_type": "rule",
                        "hierarchy_type": "rule",
                        "pdf_name": "part.pdf",
                        "candidate_title": "Test Rules, 2020",
                        "candidate_dates": ["1st January, 2020"],
                        "candidate_departments": ["MINISTRY OF TESTS"],
                        "candidate_gazette_ids": ["1 GI/2020"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    specs = specs_from_manifest(manifest)

    assert len(specs) == 1
    assert specs[0].filename == "part_1.txt"
    assert specs[0].source_type == "rule"
    assert specs[0].title_hint == "Test Rules, 2020"
    assert specs[0].metadata == {
        "candidate_dates": ["1st January, 2020"],
        "candidate_departments": ["MINISTRY OF TESTS"],
        "candidate_gazette_ids": ["1 GI/2020"],
    }


def test_build_drafts_from_manifest_uses_text_dir_and_title_hint(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "originals").mkdir()
    text_dir = tmp_path / "texts"
    text_dir.mkdir()
    _write(text_dir / "part_1.txt", "===== PAGE 1 =====\n1. A.\n2. B.\n")
    manifest = tmp_path / "metadata.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": "part_1.txt",
                        "source_id": "PART_1",
                        "source_type": "rule",
                        "hierarchy_type": "rule",
                        "pdf_name": "part.pdf",
                        "candidate_title": "Test Rules, 2020",
                        "candidate_dates": ["1st January, 2020"],
                        "candidate_departments": ["MINISTRY OF TESTS"],
                        "candidate_gazette_ids": ["1 GI/2020"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    build = build_drafts(
        corpus_dir,
        out_dir=tmp_path / "draft",
        manifest_path=manifest,
        text_dir=text_dir,
    )

    assert len(build.sources) == 1
    assert build.sources[0].title == "Test Rules, 2020"
    assert build.sources[0].review_status == "unverified"
    assert build.reports[0].candidate_dates == ["1st January, 2020"]
    assert build.reports[0].candidate_gazette_ids == ["1 GI/2020"]
    with (build.out_dir / "sources_review.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        row = next(csv.DictReader(handle))
    assert row["title_status"] == "candidate"
    assert row["candidate_dates"] == "1st January, 2020"
    assert row["official_url"] == ""


def _provision(provision_id: str, text: str) -> Provision:
    return Provision(
        provision_id=provision_id,
        source_id="TEST_ACT",
        citation="TEST_ACT test",
        hierarchy_type="section",
        parent_provision_id=None,
        original_text=text,
        search_text="",
        provisos=[],
        exceptions=[],
        definitions_used=[],
        cross_references=[],
        mandatory_context=[],
        conditions=[],
        page_start=1,
        page_end=1,
    )


def test_provision_flags_are_mechanical_and_conservative():
    assert _provision_flags(
        _provision("TEST_ACT_P001", "A complete sentence that is long enough to review.")
    ) == []
    assert "short_text" in _provision_flags(_provision("TEST_ACT_P002", "1. Short."))
    assert "starts_lowercase" in _provision_flags(
        _provision("TEST_ACT_P003", "lowercase start but otherwise a full sentence.")
    )
    assert "devanagari" in _provision_flags(
        _provision("TEST_ACT_P004", "Mixed text with \u0915\u0947\u0902\u0926\u094d\u0930\u0940\u092f characters.")
    )
    assert "replacement_char" in _provision_flags(
        _provision("TEST_ACT_P005", "Text with a broken \ufffd character inside.")
    )


def test_section_gaps_reports_missing_numbers():
    provisions = [
        _provision("TEST_ACT_P001", "First."),
        _provision("TEST_ACT_P003", "Third."),
    ]
    gaps, numbers = _section_gaps(provisions)

    assert numbers == [1, 3]
    assert gaps == [2]
