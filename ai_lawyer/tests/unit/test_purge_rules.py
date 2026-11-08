"""REAL_RAG_BUILD.md purge rules: synthetic data must not leak into real mode."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from ai_lawyer.config.settings import Settings
from ai_lawyer.evaluation import run_behavior_eval
from ai_lawyer.evaluation.run_behavior_eval import dataset_origin
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.embedders import RealModeEmbedderRefused, get_embedder
from ai_lawyer.tests.unit.test_machine_verification import PROVISION, SOURCE, _write

PACKAGE = Path(__file__).resolve().parents[2]
FIXTURE = PACKAGE / "legal_corpus" / "fixture"
DATASETS = PACKAGE / "evaluation" / "dataset"


def _fixture_provision_id() -> str:
    return json.loads((FIXTURE / "provisions.json").read_text(encoding="utf-8"))[0]["provision_id"]


def test_real_mode_refuses_an_injected_fixture_provision_id(tmp_path):
    leaked = {**deepcopy(PROVISION), "provision_id": _fixture_provision_id()}
    _write(tmp_path, [deepcopy(SOURCE)], [deepcopy(PROVISION), leaked])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)
    assert any("fixture provision id" in e for e in exc.value.errors)


@pytest.mark.parametrize("marker", ["TEST_ACT", "FIXTURE DATA", "FAKE TEST TEXT"])
def test_real_mode_refuses_fixture_markers_in_text(tmp_path, marker):
    provision = {**deepcopy(PROVISION), "original_text": f"{marker}: a seller must refund."}
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)
    assert any(marker in e for e in exc.value.errors)


def test_fixture_corpus_lives_in_its_own_folder_and_real_mode_never_reads_it():
    assert (FIXTURE / "sources.json").exists()
    assert not (PACKAGE / "legal_corpus" / "fixture_sources.json").exists()
    assert not (PACKAGE / "legal_corpus" / "fixture_provisions.json").exists()


def test_real_mode_refuses_the_hashed_embedder():
    with pytest.raises(RealModeEmbedderRefused):
        get_embedder(Settings(corpus_mode="real", embedding_backend="hash"))


def test_fakes_live_under_tests_and_runtime_never_imports_them_at_module_level():
    assert not (PACKAGE / "contracts" / "fakes.py").exists()
    offenders = []
    for folder in ("backend", "legal_rag", "legal_engine", "frontend", "documents", "contracts", "config"):
        for path in (PACKAGE / folder).rglob("*.py"):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if re.match(r"^(from|import) ai_lawyer\.tests", line):
                    offenders.append(f"{path.relative_to(PACKAGE)}: {line}")
    assert offenders == []


def test_every_dataset_row_is_tagged_with_its_origin():
    for name in ("behavior_cases.jsonl", "retrieval_stories_to_label.jsonl", "development.jsonl", "test.jsonl"):
        rows = [json.loads(line) for line in (DATASETS / name).read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows, name
        assert all(str(r.get("data_origin", "")).startswith("synthetic") for r in rows), name


def test_mixed_or_untagged_origins_are_refused():
    assert dataset_origin([{"data_origin": "synthetic_written"}, {"data_origin": "user_supplied"}])[1]
    assert dataset_origin([{"test_id": "x"}])[1]
    assert dataset_origin([{"data_origin": "public_commission_order"}]) == ("public_commission_order", None)


def test_real_behaviour_run_on_synthetic_stories_needs_a_separate_table(capsys):
    code = run_behavior_eval.main(["--mode", "real"])

    assert code == 2
    assert "--synthetic-table" in capsys.readouterr().out
