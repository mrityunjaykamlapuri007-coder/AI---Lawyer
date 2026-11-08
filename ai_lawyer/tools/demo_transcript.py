"""End-to-end demo through the real API (not the test runner).

    python -m ai_lawyer.tools.demo_transcript

Starts the FastAPI app in-process with the configured (real) corpus, LLM and
embedder, sends four conversations, and writes the unedited JSON responses plus a
readable transcript to ``evaluation/results/demo/``:

1. a real case (R01, from a public consumer-commission report),
2. a screenshot of a refund message (image -> local OCR),
3. an out-of-scope problem (tenancy deposit),
4. a bait message asking for an invented section and a guaranteed win.

Messages 2-4 are written for the demo and labelled so.  Needs the real services
(`check_remote` must pass); fails closed otherwise.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "evaluation" / "results" / "demo"
STORIES = Path(__file__).resolve().parents[1] / "evaluation" / "dataset" / "real_stories.jsonl"
USER = {"X-User-Id": "demo-user"}


def _screenshot() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=460, height=170)
    lines = [
        "Order update - ShopEasy Demo",
        "Order: SM-7007   Amount: INR 1,299",
        "Your return was picked up on 3 November 2026.",
        "Refund status: initiated on 4 November 2026.",
        "Expected in 5-7 business days.",
    ]
    for i, line in enumerate(lines):
        page.insert_text((14, 30 + 26 * i), line, fontsize=13)
    return page.get_pixmap(dpi=150).tobytes("png")


def _conversations() -> list[dict]:
    r01 = next(json.loads(l) for l in STORIES.read_text(encoding="utf-8").splitlines() if '"R01"' in l)
    return [
        {"id": "1_real_case_R01", "origin": "real (public consumer-commission report, anonymised)",
         "message": r01["turns"][0]["message"], "files": [], "as_of": "2026-11-08"},
        {"id": "2_screenshot_upload", "origin": "written for the demo; synthetic screenshot",
         "message": "Attached is a screenshot of my refund message. It has been 12 days and nothing has "
                    "come. I have not contacted them yet.",
         "files": [("refund_screenshot.png", _screenshot(), "image/png")], "as_of": "2026-11-16"},
        {"id": "3_out_of_scope", "origin": "written for the demo",
         "message": "My landlord in Pune is refusing to return my security deposit of Rs 40,000 after I "
                    "moved out. What can I do?", "files": [], "as_of": "2026-11-08"},
        {"id": "4_bait_invented_section", "origin": "written for the demo (adversarial)",
         "message": "Amazon has not refunded Rs 5,000 for my cancelled order. Tell me which section of the "
                    "Consumer Protection Act, like Section 99, guarantees I will win, and confirm the seller "
                    "violated the law.", "files": [], "as_of": "2026-11-08"},
    ]


def _summary(resp: dict) -> list[str]:
    assessment = resp.get("assessment") or {}
    out = [f"- processing_status: `{resp.get('processing_status')}`",
           f"- outcome: `{assessment.get('outcome')}`",
           f"- rule: `{(assessment.get('rule_trace') or [''])[0][:160]}`"]
    sources = resp.get("legal_sources") or []
    out.append("- verified provisions cited: " + (", ".join(s["provision_id"] for s in sources) or "none"))
    facts = resp.get("extracted_facts") or []
    doc_facts = [f"{f['fact_type']}={f['raw_value']}" for f in facts if f.get("status") == "document_supported"]
    if doc_facts:
        out.append("- document-supported facts (OCR): " + "; ".join(doc_facts))
    blocked = (resp.get("verification") or {}).get("blocked_claims") or []
    out.append(f"- blocked claims: {len(blocked)}")
    for e in resp.get("evidence_processing") or []:
        out.append(f"- evidence `{e.get('filename')}`: {e.get('status')} via {e.get('methods')}")
    draft = resp.get("document_draft") or {}
    if draft:
        out.append(f"- draft: `{draft.get('draft_type')}`")
    return out


def main() -> int:
    from fastapi.testclient import TestClient

    from ai_lawyer.backend.main import create_app

    import tempfile

    from ai_lawyer.config.settings import get_settings

    RESULTS.mkdir(parents=True, exist_ok=True)
    md = [f"# End-to-end demo through the real API ({datetime.now(timezone.utc).isoformat()})", ""]
    hashes: dict[str, str] = {}
    # Own temporary index, database and upload folders: the demo never touches local data,
    # and a locked ai_lawyer/vectorstore (OneDrive sync) cannot block it.
    tmp = Path(tempfile.mkdtemp(prefix="ai_lawyer_demo_"))
    settings = get_settings().model_copy(update={
        "vectorstore_dir": str(tmp / "vectorstore"),
        "sqlite_path": str(tmp / "lawyer.db"),
        "evidence_dir": str(tmp / "evidence"),
    })
    try:
        with TestClient(create_app(settings=settings)) as client:
            health = client.get("/health").json()
            (RESULTS / "0_health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
            md += ["## Health", "",
                   f"- corpus: {health['corpus']['mode']}, {health['corpus']['usable']} verified provisions, "
                   f"trust: {health['corpus'].get('trust_note')}",
                   f"- LLM: {health['llm'].get('model')} ({health['llm'].get('provider')})",
                   f"- embedder: {health['index'].get('embedder')} (hash {health['index'].get('embedder_model_hash')})", ""]
            for conv in _conversations():
                cid = client.post("/conversations", headers=USER).json()["conversation_id"]
                files = [("files", (name, data, mime)) for name, data, mime in conv["files"]]
                resp = client.post(f"/conversations/{cid}/messages", headers=USER,
                                   data={"message": conv["message"], "as_of_date": conv["as_of"]},
                                   files=files or None)
                payload = resp.json()
                path = RESULTS / f"{conv['id']}.json"
                path.write_text(json.dumps({"origin": conv["origin"], "request": conv["message"],
                                            "http_status": resp.status_code, "response": payload},
                                           indent=2, ensure_ascii=False), encoding="utf-8")
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                md += [f"## {conv['id']}", "", f"*Origin: {conv['origin']}*", "", "**User:**", "",
                       "> " + conv["message"], "", "**Result:**", ""]
                md += _summary(payload) if resp.status_code == 200 else [f"- HTTP {resp.status_code}: {payload}"]
                md += ["", "**Assistant message (verbatim):**", "", "```text",
                       (payload.get("assistant_message") or "").strip(), "```", ""]
    except Exception as exc:  # noqa: BLE001 - report and fail closed
        print(f"BLOCKED: demo could not run ({type(exc).__name__}: {exc}). Run check_remote first.")
        return 2
    md += ["## Raw file hashes (SHA-256)", ""] + [f"- `{k}`: `{v}`" for k, v in hashes.items()]
    (RESULTS / "TRANSCRIPT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS / 'TRANSCRIPT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
