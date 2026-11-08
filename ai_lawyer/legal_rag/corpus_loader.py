"""Corpus loading, validation and manifest generation.

The loader is the only route by which legal text enters the system.  Every
citation shown to a user is rendered from these objects, never from a model.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.contracts.ids import utc_now
from ai_lawyer.contracts.models import CorpusManifest, Provision, Source

logger = logging.getLogger(__name__)

ALLOWED_OPERATORS = {"exists", "equals", "in", "date_before", "date_after", "manual"}


def provision_is_usable(source: Source | None, provision: Provision) -> bool:
    """A provision is citable only when both it and its source were approved.

    ``human_verified`` on a source says the document is the right document.
    It says nothing about whether a human read this particular provision, so a
    per-provision approval with a named reviewer is also required.
    """
    if source is None:
        return False
    if source.review_status != "human_verified":
        return False
    if provision.review_status != "human_verified":
        return False
    return bool(provision.reviewed_by and provision.reviewed_by.strip())


@dataclass
class Corpus:
    sources: dict[str, Source]
    provisions: dict[str, Provision]
    mode: str
    corpus_version: str
    manifest: CorpusManifest
    warnings: list[str] = field(default_factory=list)

    def get(self, provision_id: str) -> Provision | None:
        return self.provisions.get(provision_id)

    def source_for(self, provision: Provision) -> Source:
        return self.sources[provision.source_id]

    def children(self, provision_id: str) -> list[str]:
        return [
            p.provision_id
            for p in self.provisions.values()
            if p.parent_provision_id == provision_id
        ]

    def usable_ids(self) -> set[str]:
        return {
            pid
            for pid, p in self.provisions.items()
            if provision_is_usable(self.sources.get(p.source_id), p)
        }

    def is_usable(self, provision_id: str) -> bool:
        p = self.provisions.get(provision_id)
        if p is None:
            return False
        return provision_is_usable(self.sources.get(p.source_id), p)

    @property
    def usable_count(self) -> int:
        return len(self.usable_ids())

    @property
    def unusable_count(self) -> int:
        return len(self.provisions) - self.usable_count

    def all_provisions(self) -> list[Provision]:
        return list(self.provisions.values())


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise CorpusValidationError([f"missing corpus file: {path}"])
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusValidationError([f"invalid JSON in {path}: {exc}"]) from exc


def _canonical_hash(sources: list[Source], provisions: list[Provision]) -> str:
    payload = {
        "sources": sorted(
            [s.model_dump(mode="json") for s in sources], key=lambda x: x["source_id"]
        ),
        "provisions": sorted(
            [p.model_dump(mode="json") for p in provisions], key=lambda x: x["provision_id"]
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_corpus(
    mode: str | None = None,
    corpus_dir: str | Path | None = None,
    settings: Settings | None = None,
) -> Corpus:
    """Load and validate the real or fixture corpus."""
    settings = settings or get_settings()
    mode = mode or settings.corpus_mode
    directory = Path(corpus_dir or settings.corpus_path)

    if mode == "fixture":
        sources_path = directory / "fixture_sources.json"
        provisions_path = directory / "fixture_provisions.json"
    elif mode == "real":
        sources_path = directory / "sources.json"
        provisions_path = directory / "provisions.json"
    else:
        raise CorpusValidationError([f"unknown CORPUS_MODE: {mode}"])

    raw_sources = _read_json(sources_path)
    raw_provisions = _read_json(provisions_path)
    corpus = validate_and_build(
        raw_sources, raw_provisions, mode=mode, directory=directory
    )
    if mode == "real":
        # Imported lazily to avoid a circular import: the gate imports this
        # module for the Corpus type only.
        from ai_lawyer.legal_rag.corpus_acceptance import enforce_real_corpus_acceptance

        enforce_real_corpus_acceptance(corpus)
    return corpus


def validate_and_build(
    raw_sources: Any,
    raw_provisions: Any,
    *,
    mode: str = "fixture",
    directory: Path | None = None,
    warn_unusable: bool = True,
) -> Corpus:
    errors: list[str] = []
    if not isinstance(raw_sources, list):
        errors.append("sources file must be a JSON list")
    if not isinstance(raw_provisions, list):
        errors.append("provisions file must be a JSON list")
    if errors:
        raise CorpusValidationError(errors)

    sources: dict[str, Source] = {}
    for i, item in enumerate(raw_sources):
        try:
            source = Source.model_validate(item)
        except ValidationError as exc:
            errors.append(f"source[{i}] invalid: {exc.errors()}")
            continue
        if source.source_id in sources:
            errors.append(f"duplicate source_id: {source.source_id}")
            continue
        sources[source.source_id] = source

    provisions: dict[str, Provision] = {}
    for i, item in enumerate(raw_provisions):
        try:
            provision = Provision.model_validate(item)
        except ValidationError as exc:
            errors.append(f"provision[{i}] invalid: {exc.errors()}")
            continue
        if provision.provision_id in provisions:
            errors.append(f"duplicate provision_id: {provision.provision_id}")
            continue
        if not provision.original_text.strip():
            errors.append(f"missing original_text: {provision.provision_id}")
            continue
        provisions[provision.provision_id] = provision

    # Reference integrity.
    for pid, provision in provisions.items():
        if provision.source_id not in sources:
            errors.append(f"provision {pid} references unknown source_id {provision.source_id}")
        refs: list[tuple[str, str]] = []
        if provision.parent_provision_id:
            refs.append(("parent_provision_id", provision.parent_provision_id))
        refs += [("proviso", r) for r in provision.provisos]
        refs += [("exception", r) for r in provision.exceptions]
        refs += [("definition", r) for r in provision.definitions_used]
        refs += [("cross_reference", r) for r in provision.cross_references]
        refs += [("mandatory_context", r) for r in provision.mandatory_context]
        for label, ref in refs:
            if ref not in provisions:
                errors.append(f"{pid} has dangling {label}: {ref}")
        for condition in provision.conditions:
            if condition.operator not in ALLOWED_OPERATORS:
                errors.append(
                    f"{pid} condition {condition.condition_id} has invalid operator "
                    f"{condition.operator!r}"
                )

    if errors:
        raise CorpusValidationError(errors)

    corpus_version = _canonical_hash(list(sources.values()), list(provisions.values()))
    usable_count = sum(
        1
        for p in provisions.values()
        if provision_is_usable(sources.get(p.source_id), p)
    )
    manifest = CorpusManifest(
        corpus_version=corpus_version,
        mode=mode,  # type: ignore[arg-type]
        sources_count=len(sources),
        provisions_count=len(provisions),
        usable_count=usable_count,
        unusable_count=len(provisions) - usable_count,
        generated_at=utc_now(),
    )
    corpus = Corpus(
        sources=sources,
        provisions=provisions,
        mode=mode,
        corpus_version=corpus_version,
        manifest=manifest,
    )
    if corpus.unusable_count:
        msg = (
            f"{corpus.unusable_count} of {len(provisions)} provisions are loaded but "
            "unusable because the provision and its source are not both human_verified; "
            "they will not be cited."
        )
        corpus.warnings.append(msg)
        if warn_unusable:
            logger.warning(msg)
    if directory is not None:
        write_manifest(corpus, directory)
    return corpus


def write_manifest(corpus: Corpus, directory: str | Path) -> Path:
    path = Path(directory) / "corpus_manifest.json"
    path.write_text(
        json.dumps(corpus.manifest.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def startup_summary(corpus: Corpus) -> str:
    return (
        f"CORPUS_MODE={corpus.mode} version={corpus.corpus_version} "
        f"sources={len(corpus.sources)} provisions={len(corpus.provisions)} "
        f"usable={corpus.usable_count} unusable={corpus.unusable_count}"
    )
