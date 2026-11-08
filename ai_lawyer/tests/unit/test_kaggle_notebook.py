from __future__ import annotations

import json
import re
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[3] / "kaggle" / "serve_llm.ipynb"


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_notebook_is_valid_json_with_code_cells():
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    assert len(notebook["cells"]) >= 8
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) >= 7
    assert all(isinstance(c["source"], list) for c in notebook["cells"])


def test_notebook_reads_secrets_and_never_hardcodes_tokens():
    text = "\n".join("".join(c["source"]) for c in _notebook()["cells"])
    assert "UserSecretsClient" in text
    assert "get_secret" in text
    # No Hugging Face token or bearer token literal anywhere.
    assert not re.search(r"hf_[A-Za-z0-9]{20,}", text)
    assert not re.search(r"Bearer\s+[A-Za-z0-9_\-]{20,}", text)
    assert 'API_KEY = "' not in text


def test_notebook_uses_json_schema_and_a_tunnel():
    text = "\n".join("".join(c["source"]) for c in _notebook()["cells"])
    assert "response_format" in text
    assert "json_schema" in text
    assert "cloudflared" in text
    assert "/v1/models" in text
    assert "max-model-len" in text
    assert "tensor-parallel-size" in text


def test_notebook_refuses_fp16_8b_on_a_single_gpu():
    text = "\n".join("".join(c["source"]) for c in _notebook()["cells"])
    assert "cannot hold fp16 8B" in text
