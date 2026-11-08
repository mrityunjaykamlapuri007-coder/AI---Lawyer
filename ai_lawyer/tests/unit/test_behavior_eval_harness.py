from __future__ import annotations

from types import SimpleNamespace

from ai_lawyer.evaluation import run_behavior_eval as harness


def _corpus_with(provisions):
    usable = {pid: True for pid in provisions}
    corpus = SimpleNamespace(
        provisions={
            pid: SimpleNamespace(
                citation=row["citation"], original_text=row["original_text"]
            )
            for pid, row in provisions.items()
        },
        usable_ids=lambda: set(usable),
    )
    return corpus


def test_section_numbers_in_verified_corpus_are_allowed():
    corpus = _corpus_with(
        {
            "P1": {"citation": "Section 35 of the Act", "original_text": "..."},
            "P2": {"citation": "Rule 4", "original_text": "..."},
        }
    )
    allowed = harness._usable_section_numbers(corpus)
    assert allowed == {"35", "4"}


def test_section_number_absent_from_corpus_is_flagged():
    corpus = _corpus_with(
        {"P1": {"citation": "Section 35 of the Act", "original_text": "..."}}
    )
    responses = [
        {"assistant_message": "Under Section 35 you may complain."},
        {"assistant_message": "Ignore Section 99; it is invented."},
    ]

    defects = harness._unverified_section_numbers(responses, corpus)

    assert defects == ["Section 99"]


def test_section_number_detection_ignores_plain_numbers():
    corpus = _corpus_with({"P1": {"citation": "Section 2", "original_text": "..."}})
    responses = [{"assistant_message": "Wait 12 days, then call 1800-123-4567."}]

    assert harness._unverified_section_numbers(responses, corpus) == []


def test_real_mode_refuses_when_no_runtime_corpus_exists(capsys):
    code = harness.main(["--mode", "real"])

    output = capsys.readouterr().out
    assert code == 2
    assert "BLOCKED" in output
    assert "sources.json" in output
