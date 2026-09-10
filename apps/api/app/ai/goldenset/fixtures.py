from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .spans import GoldenSpan


@dataclass(frozen=True)
class GoldenDocument:
    document_id: str
    path: str
    role: str
    sha256: str | None = None


@dataclass(frozen=True)
class GoldenCase:
    notice_no: str
    documents: tuple[GoldenDocument, ...]
    spans: tuple[GoldenSpan, ...]
    profile_path: str | None = None
    reference_date: str | None = None


def load_cases(root: Path) -> list[GoldenCase]:
    payload = json.loads((root / "spans.json").read_text(encoding="utf-8"))
    cases: list[GoldenCase] = []
    for raw_case in payload.get("cases", []):
        cases.append(
            GoldenCase(
                notice_no=raw_case["notice_no"],
                documents=tuple(GoldenDocument(**item) for item in raw_case["documents"]),
                spans=tuple(GoldenSpan(**item) for item in raw_case["spans"]),
                profile_path=raw_case.get("profile_path"),
                reference_date=raw_case.get("reference_date"),
            )
        )
    return cases


def load_case_chunks(
    case: GoldenCase,
    *,
    repo_root: Path,
    chunker: str = "default",
) -> list[dict[str, Any]]:
    """Extract cached fixtures through the same adapter used by the demo."""
    from ..demo.documents import FetchedDocument, G2BDocumentSource
    from ..qualification.extraction.chunking import (
        chunk_source_blocks,
        chunk_source_blocks_hygienic,
    )

    chunkers = {
        "default": chunk_source_blocks,
        "hygienic": chunk_source_blocks_hygienic,
    }
    try:
        chunk_source = chunkers[chunker]
    except KeyError as error:
        raise ValueError(f"unknown chunker: {chunker}") from error

    chunks: list[dict[str, Any]] = []
    source = G2BDocumentSource()
    for document in case.documents:
        path = repo_root / document.path
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        fetched = FetchedDocument(
            url=meta.get("url", ""),
            filename=meta.get("filename") or path.name,
            content_type=meta.get("content_type"),
        )
        source._extract(fetched, path.read_bytes())
        if fetched.error:
            raise ValueError(f"{document.document_id}: {fetched.error}")
        blocks = [
            {**block, "document_id": document.document_id, "document_role": document.role}
            for block in fetched.blocks
        ]
        for chunk in chunk_source(blocks):
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
    return chunks
