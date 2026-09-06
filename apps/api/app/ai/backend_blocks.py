"""Adapters for backend-managed extracted document blocks.

Backend document extraction is the source of truth for file parsing and source
locations. Semantic chunking must preserve those locators instead of flattening
them away.
"""

from __future__ import annotations

from typing import Any


def canonical_source_block(
    *,
    document_id: str,
    text_sha256: str | None,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a backend extracted block without discarding source location."""
    return {
        "document_id": document_id,
        "block_index": block.get("block_index"),
        "page": block.get("page"),
        "section_index": block.get("section_index"),
        "paragraph_index": block.get("paragraph_index"),
        "location": block.get("location"),
        "text": (block.get("text") or "").strip(),
        "source_sha256": text_sha256,
    }


def canonical_source_blocks(
    *,
    document_id: str,
    text_sha256: str | None,
    blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not blocks:
        return []
    return [
        canonical_source_block(
            document_id=document_id,
            text_sha256=text_sha256,
            block=block,
        )
        for block in blocks
        if (block.get("text") or "").strip()
    ]
