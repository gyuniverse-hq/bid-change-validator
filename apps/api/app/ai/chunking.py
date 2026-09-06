"""Semantic chunking over backend extracted blocks.

This ports the useful clause-heading idea from the LLM/RAG PoC while keeping
backend document/page/section/paragraph locators attached to every chunk.
"""

from __future__ import annotations

import re
from typing import Any

_HEADING_PATTERNS = [
    re.compile(r"^\s*(제\d+조(?:의\d+)?)\s*[(\s]"),
    re.compile(r"^\s*(제\d+장)\s"),
    re.compile(r"^\s*(\d+(?:\.\d+)+)[.)]?\s+"),
    re.compile(r"^\s*(\d+)[.)]\s+"),
    re.compile(r"^\s*([IVXivx]+)\.\s+"),
    re.compile(r"^\s*([가-힣])[.)]\s+"),
]


def _heading(line: str) -> str | None:
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def chunk_source_blocks(
    blocks: list[dict[str, Any]],
    *,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    """Create semantic chunks while retaining all source block locators."""
    chunks: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_sources: list[dict[str, Any]] = []
    current_label: str | None = None

    def flush() -> None:
        nonlocal current_text, current_sources, current_label
        text = "\n".join(current_text).strip()
        if text:
            chunks.append(
                {
                    "chunk_id": f"CHUNK-{len(chunks):04d}",
                    "clause_label": current_label,
                    "text": text,
                    "source_blocks": list(current_sources),
                }
            )
        current_text = []
        current_sources = []

    for block in blocks:
        block_text = (block.get("text") or "").strip()
        if not block_text:
            continue
        lines = block_text.splitlines() or [block_text]
        first_label = _heading(lines[0])
        if first_label is not None and current_text:
            flush()
        if first_label is not None:
            current_label = first_label
        current_text.append(block_text)
        current_sources.append(block)
        if sum(len(part) for part in current_text) >= max_chars:
            flush()
    flush()
    return chunks
