"""Official-copy check: the source PDF must equal the Gazette of India copy.

Machine verification (V1-V6) compares a PDF with itself: text layer against OCR
of the same file.  That cannot catch a file that is not the authoritative
publication.  This check downloads the copy published on the e-Gazette and
requires it to be byte-identical (same SHA-256) to the file in ``originals/``.

Only the e-Gazette host is accepted.  A ministry mirror, a court site or a law
blog is a different publisher and does not count, even if the bytes match.

Usage::

    python -m ai_lawyer.legal_rag.official_copy --source ECR_2020 \\
        --url https://egazette.gov.in/WriteReadData/2020/220661.pdf

The result is written to the staging source record (``official_copy``) and to
``official/verification/<source_id>/official_copy.json``.  The network is used
only by this command; tests inject a fake fetcher.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

PACKAGE_DIR = Path(__file__).resolve().parents[1]
OFFICIAL = PACKAGE_DIR / "legal_corpus" / "official"
DEFAULT_STAGING = OFFICIAL / "draft_curated"
ORIGINALS_DIR = OFFICIAL / "originals"
OUT_DIR = OFFICIAL / "verification"

# The Gazette of India.  egazette.nic.in no longer resolves; its files are
# served from egazette.gov.in under the same paths.
OFFICIAL_HOSTS = frozenset({"egazette.gov.in"})

# (final_url, http_status, body)
Fetcher = Callable[[str], tuple[str, int, bytes]]


class RefusedUrl(ValueError):
    pass


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _require_official(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RefusedUrl(f"not an https URL: {url}")
    if _host(url) not in OFFICIAL_HOSTS:
        raise RefusedUrl(
            f"host {_host(url)!r} is not an official Gazette host "
            f"({', '.join(sorted(OFFICIAL_HOSTS))})"
        )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _http_fetch(url: str) -> tuple[str, int, bytes]:
    import ssl

    import httpx  # lazy: no network library work at import time
    import truststore

    # egazette.gov.in serves an incomplete certificate chain.  The OS trust
    # store completes it the way a browser does; verification stays ON.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(
        follow_redirects=True,
        timeout=120,
        verify=context,
        headers={"User-Agent": "ai-lawyer-corpus-check/1.0"},
    ) as client:
        response = client.get(url)
        return str(response.url), response.status_code, response.content


def check_official_copy(
    local_pdf: Path, url: str, *, fetch: Fetcher | None = None
) -> dict[str, Any]:
    """Download ``url`` and compare it byte for byte with ``local_pdf``.

    Raises ``RefusedUrl`` for a non-official host before any request is made.
    Every other outcome is returned as evidence, never raised.
    """
    _require_official(url)
    local_sha = _sha256_file(local_pdf)
    evidence: dict[str, Any] = {
        "url": url,
        "host": _host(url),
        "local_file": local_pdf.name,
        "local_sha256": local_sha,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        final_url, status, body = (fetch or _http_fetch)(url)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        evidence.update(result="fetch_failed", error=type(exc).__name__)
        return evidence

    evidence.update(final_url=final_url, http_status=status, bytes=len(body))
    if _host(final_url) not in OFFICIAL_HOSTS:
        evidence["result"] = "redirected_off_official_host"
        return evidence
    if status != 200:
        evidence["result"] = "fetch_failed"
        return evidence
    if not body.startswith(b"%PDF"):
        evidence["result"] = "not_a_pdf"
        return evidence

    evidence["sha256"] = _sha256_bytes(body)
    evidence["result"] = "byte_identical" if evidence["sha256"] == local_sha else "mismatch"
    return evidence


def official_copy_problems(
    source_id: str,
    official_copy: dict[str, Any] | None,
    document_sha256: str | None,
) -> list[str]:
    """Reasons a source's official-copy evidence is not acceptable."""
    if not official_copy:
        return [f"source {source_id} has no official Gazette copy check"]
    problems: list[str] = []
    if official_copy.get("result") != "byte_identical":
        problems.append(
            f"source {source_id} official copy check result is "
            f"{official_copy.get('result')!r}, not 'byte_identical'"
        )
    for key in ("host", "final_url"):
        value = official_copy.get(key)
        host = value if key == "host" else _host(str(value or ""))
        if host not in OFFICIAL_HOSTS:
            problems.append(f"source {source_id} official copy {key} is not an official Gazette host")
    sha = official_copy.get("sha256")
    if not sha or sha != official_copy.get("local_sha256"):
        problems.append(f"source {source_id} official copy hash does not match the local file")
    if not document_sha256 or sha != document_sha256:
        problems.append(
            f"source {source_id} official copy hash does not match document_sha256"
        )
    return problems


def _local_pdf_for(source_id: str) -> Path:
    # Same resolution as machine_verify, so both checks look at one file.
    from ai_lawyer.legal_rag.machine_verify import _document_metadata

    document = _document_metadata(source_id)
    name = document.get("pdf_name") or document.get("file") or ""
    path = ORIGINALS_DIR / name if name else None
    if not path or not path.exists():
        raise FileNotFoundError(f"original PDF for {source_id} not found ({name!r})")
    return path


def record(
    source_id: str,
    url: str,
    staging: Path,
    *,
    fetch: Fetcher | None = None,
    local_pdf: Path | None = None,
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    sources_path = staging / "draft_sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    source = next((s for s in sources if s.get("source_id") == source_id), None)
    if source is None:
        raise KeyError(f"unknown source_id: {source_id}")

    evidence = check_official_copy(local_pdf or _local_pdf_for(source_id), url, fetch=fetch)
    source["official_copy"] = evidence
    sources_path.write_text(
        json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    target = out_dir / source_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "official_copy.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.legal_rag.official_copy",
        description="Compare a source PDF with its Gazette of India copy.",
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--url", required=True, help="e-Gazette PDF URL")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    args = parser.parse_args(argv)

    try:
        evidence = record(args.source, args.url, args.staging_dir)
    except (RefusedUrl, KeyError, FileNotFoundError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"source : {args.source}")
    print(f"url    : {evidence['url']}")
    print(f"status : {evidence.get('http_status')}  bytes: {evidence.get('bytes')}")
    print(f"local  : {evidence['local_sha256']}")
    print(f"gazette: {evidence.get('sha256')}")
    print(f"result : {evidence['result']}")
    return 0 if evidence["result"] == "byte_identical" else 1


if __name__ == "__main__":
    raise SystemExit(main())
