"""Propose qualification spans from cached documents for human labeling."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..ai.goldenset.spans import squash
from ..ai.demo.documents import FetchedDocument, G2BDocumentSource


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE = REPO_ROOT / "data" / "demo" / "notice-documents"

QUALIFICATION_KEYWORDS = (
    "참가자격",
    "입찰참가자격",
    "자격요건",
    "업종코드",
    "등록",
    "면허",
    "직접생산",
    "실적",
    "기술인력",
    "소기업",
    "중소기업",
    "중견기업",
    "대기업",
    "지역제한",
)
TRAP_TERMS = ("누출", "처벌", "제재", "취소", "감점", "평가", "배점")


@dataclass(frozen=True)
class SpanProposal:
    notice_no: str
    document_id: str
    document_name: str
    suggested_role: str
    review_hint: str
    keywords: tuple[str, ...]
    quote: str


def _role_for_name(filename: str) -> str:
    normalized = filename.replace(" ", "")
    if "제안요청" in normalized or "과업" in normalized:
        return "RFP"
    if "공고" in normalized:
        return "NOTICE"
    if any(word in normalized for word in ("서식", "양식", "별지")):
        return "FORM"
    return "REVIEW"


def _candidate_windows(text: str, *, radius: int = 180) -> Iterable[str]:
    normalized = " ".join(text.split())
    lowered = normalized.casefold()
    for keyword in QUALIFICATION_KEYWORDS:
        start_at = 0
        while True:
            index = lowered.find(keyword.casefold(), start_at)
            if index < 0:
                break
            start = max(0, index - radius)
            end = min(len(normalized), index + len(keyword) + radius)
            # Prefer sentence boundaries while retaining a bounded fallback.
            left = max(normalized.rfind(mark, start, index) for mark in (".", "다.", ";"))
            right_candidates = [
                position
                for mark in (".", "다.", ";")
                if (position := normalized.find(mark, index + len(keyword), end)) >= 0
            ]
            if left >= start:
                start = left + 1
            if right_candidates:
                end = min(right_candidates) + 2
            quote = normalized[start:end].strip(" ;")
            if quote:
                yield quote
            start_at = index + len(keyword)


def propose_from_text(
    *,
    notice_no: str,
    document_id: str,
    document_name: str,
    text: str,
    max_candidates: int = 30,
) -> list[SpanProposal]:
    proposals: list[SpanProposal] = []
    seen: set[str] = set()
    for quote in _candidate_windows(text):
        key = squash(quote)
        if not key or key in seen:
            continue
        seen.add(key)
        keywords = tuple(word for word in QUALIFICATION_KEYWORDS if word in quote)
        review_hint = "LIKELY_TRAP" if any(word in quote for word in TRAP_TERMS) else "REVIEW"
        proposals.append(
            SpanProposal(
                notice_no=notice_no,
                document_id=document_id,
                document_name=document_name,
                suggested_role=_role_for_name(document_name),
                review_hint=review_hint,
                keywords=keywords,
                quote=quote,
            )
        )
        if len(proposals) >= max_candidates:
            break
    return proposals


def propose_from_cache(
    cache_root: Path,
    *,
    notice_numbers: set[str] | None = None,
    max_candidates_per_document: int = 30,
) -> list[SpanProposal]:
    proposals: list[SpanProposal] = []
    source = G2BDocumentSource(cache_dir=cache_root)
    for notice_dir in sorted(path for path in cache_root.iterdir() if path.is_dir()):
        if notice_numbers and notice_dir.name not in notice_numbers:
            continue
        for meta_path in sorted(notice_dir.glob("*.json")):
            binary_path = meta_path.with_suffix(".bin")
            if not binary_path.exists():
                continue
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched = FetchedDocument(
                url=str(metadata.get("url") or ""),
                filename=str(metadata.get("filename") or binary_path.name),
                content_type=metadata.get("content_type"),
            )
            source._extract(fetched, binary_path.read_bytes())
            if fetched.error:
                continue
            text = "\n".join(str(block.get("text") or "") for block in fetched.blocks)
            proposals.extend(
                propose_from_text(
                    notice_no=notice_dir.name,
                    document_id=meta_path.stem,
                    document_name=fetched.filename,
                    text=text,
                    max_candidates=max_candidates_per_document,
                )
            )
    return proposals


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose source spans for human POSITIVE/TRAP labeling."
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--notice", action="append", dest="notices")
    parser.add_argument("--max-per-document", type=int, default=30)
    args = parser.parse_args()
    proposals = propose_from_cache(
        args.cache_root,
        notice_numbers=set(args.notices or []) or None,
        max_candidates_per_document=max(1, args.max_per_document),
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            {"candidate_count": len(proposals), "candidates": [asdict(item) for item in proposals]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
