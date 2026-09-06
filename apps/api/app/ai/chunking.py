"""Semantic chunking over backend extracted blocks.

This ports the useful clause-heading idea from the LLM/RAG PoC while keeping
backend document/page/section/paragraph locators attached to every chunk.

PDF extraction currently produces one source block per page. A single page can
contain several clauses, so chunking must also inspect headings *inside* a source
block instead of only looking at the first line. Derived source fragments keep
the original backend locator plus line-range metadata for traceability.
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


def _split_source_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Split headings inside one backend block without losing its locator.

    Backend PDF extraction is page-based, while HWP/HWPX is usually
    section/paragraph-based. This function works for both: a one-line paragraph
    simply stays one fragment, while a multi-line PDF page can become several
    clause fragments.

    `source_line_start` / `source_line_end` are 1-based and refer to the text of
    the original backend block. They are internal trace metadata, not a new
    backend source-of-truth identifier.
    """
    block_text = (block.get("text") or "").strip()
    if not block_text:
        return []

    lines = block_text.splitlines() or [block_text]
    boundaries = [index for index, line in enumerate(lines) if _heading(line) is not None]

    # Preserve leading text before the first heading as its own fragment.
    starts: list[int] = []
    if not boundaries or boundaries[0] != 0:
        starts.append(0)
    starts.extend(boundaries)
    starts = sorted(set(starts))

    fragments: list[dict[str, Any]] = []
    for fragment_index, start in enumerate(starts):
        end = starts[fragment_index + 1] if fragment_index + 1 < len(starts) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if not text:
            continue
        fragments.append(
            {
                **block,
                "text": text,
                "fragment_index": len(fragments),
                "source_line_start": start + 1,
                "source_line_end": end,
            }
        )
    return fragments


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
        for fragment in _split_source_block(block):
            fragment_text = fragment["text"]
            first_line = fragment_text.splitlines()[0]
            fragment_label = _heading(first_line)

            if fragment_label is not None and current_text:
                flush()
            if fragment_label is not None:
                current_label = fragment_label

            current_text.append(fragment_text)
            current_sources.append(fragment)

            if sum(len(part) for part in current_text) >= max_chars:
                flush()

    flush()
    return chunks
