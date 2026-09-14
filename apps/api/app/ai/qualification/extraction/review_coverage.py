"""검토 후보의 원문 정체성과 응답 누락을 관리한다. DB/LLM 호출은 하지 않는다.

첫 단계는 기존 canonical source block을 누락 없이 후보로 등록하는 것이다.
블록 하나가 곧 자격요건 하나라는 뜻은 아니며, 키워드로 후보를 제거하지 않는다.
COMPLETE는 후보 처리 내역이 완결됐다는 뜻일 뿐 의미 정확성/참가 가능 판정이 아니다.
이 모듈만으로 기존 AnalysisStatus를 SUCCEEDED로 바꾸면 안 된다.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

CoverageStatus = Literal["COMPLETE", "INCOMPLETE", "INVALID", "EMPTY"]
DECISION_STATUSES = frozenset({"REQUIREMENT", "NOT_REQUIREMENT", "UNRESOLVED", "NEEDS_CONTEXT"})
_LOCATOR_FIELDS = (
    "block_index", "page", "section_index", "paragraph_index", "location",
    "source_line_start", "source_line_end",
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ReviewCandidate:
    candidate_id: str
    notice_version_id: str
    document_id: str
    block_index: int
    text: str
    # 입력 block.text의 Python 문자 위치 [start, end). PDF 바이트/문서 전체 위치가 아니다.
    start_offset: int
    end_offset: int
    block_text_sha256: str
    selected_blocks_sha256: str
    source_sha256: str | None
    extracted_text_sha256: str | None


@dataclass(frozen=True)
class CoverageReport:
    coverage_status: CoverageStatus
    candidate_count: int
    processed_count: int
    candidate_set_sha256: str
    requirement_candidate_ids: tuple[str, ...]
    non_requirement_candidate_ids: tuple[str, ...]
    unresolved_candidate_ids: tuple[str, ...]
    needs_context_candidate_ids: tuple[str, ...]
    missing_candidate_ids: tuple[str, ...]
    duplicate_candidate_ids: tuple[str, ...]
    unknown_candidate_ids: tuple[str, ...]
    invalid_response_indexes: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_review_candidates(
    source_blocks: Iterable[Mapping[str, Any]], *, notice_version_id: str,
) -> list[ReviewCandidate]:
    """선택된 원문 블록을 그대로 등록한다. 원문 삭제/정규화/자동 요건화는 하지 않는다.

    ID는 동일 차수/선택 원문/블록 위치에서 순서와 무관하게 재현된다.
    차수 간 요건 매칭 키는 아니다. selected_blocks_sha256 역시 전체 문서를
    읽었다는 증명이 아니라 전달받은 블록 집합의 지문이다.
    위치가 없거나 중복되면 추측해서 ID를 만들지 않고 실패한다.
    """
    _nonempty_string(notice_version_id, "notice_version_id")
    documents: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for block in source_blocks:
        if not isinstance(block, Mapping):
            raise ValueError("source block must be an object")
        document_id = _nonempty_string(block.get("document_id"), "document_id")
        index = block.get("block_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("block_index must be a non-negative integer")
        locator = (document_id, index)
        if locator in seen:
            raise ValueError(f"duplicate source block: {document_id}/{index}")
        seen.add(locator)
        text = block.get("text")
        if not isinstance(text, str):
            raise ValueError("source block text must be a string")
        row = {field: block.get(field) for field in _LOCATOR_FIELDS}
        row.update(text=text)
        for field in ("source_sha256", "extracted_text_sha256"):
            value = block.get(field)
            if value is not None:
                _nonempty_string(value, field)
            row[field] = value
        documents[document_id].append(row)

    candidates: list[ReviewCandidate] = []
    for document_id in sorted(documents):
        rows = sorted(documents[document_id], key=lambda row: row["block_index"])
        hashes: dict[str, str | None] = {}
        for field in ("source_sha256", "extracted_text_sha256"):
            values = {row[field] for row in rows if row[field] is not None}
            if len(values) > 1:
                raise ValueError(f"conflicting {field}: {document_id}")
            hashes[field] = next(iter(values)) if values else None
        snapshot = _digest({"document_id": document_id, "blocks": rows})
        for row in rows:
            text = row["text"]
            if not text.strip():
                continue
            identity = {
                "format": "review-candidates-v1", "notice_version_id": notice_version_id,
                "document_id": document_id, "selected_blocks_sha256": snapshot,
                "block_index": row["block_index"], "start": 0, "end": len(text),
            }
            candidates.append(ReviewCandidate(
                candidate_id="CAND-" + _digest(identity), notice_version_id=notice_version_id,
                document_id=document_id, block_index=row["block_index"], text=text,
                start_offset=0, end_offset=len(text),
                block_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                selected_blocks_sha256=snapshot, source_sha256=hashes["source_sha256"],
                extracted_text_sha256=hashes["extracted_text_sha256"],
            ))
    return candidates


def audit_review_coverage(
    candidates: Iterable[ReviewCandidate], responses: Iterable[object],
) -> CoverageReport:
    """모든 후보에 유효한 처리 결과가 정확히 한 번 있는지 검사한다.

    응답은 {candidate_id, status, reason?} 형태다. REQUIREMENT 이외 상태는
    reason이 필요하다. 미응답/미해결은 INCOMPLETE, 중복/외부ID/잘못된 응답은
    INVALID다. 응답 순서는 무관하다. 원문을 임의로 하나 선택해 복구하지 않는다.
    """
    items = list(candidates)
    ids = [candidate.candidate_id for candidate in items]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate ids must be unique")
    if len({candidate.notice_version_id for candidate in items}) > 1:
        raise ValueError("candidates must belong to one notice version")
    expected = set(ids)
    seen: Counter[str] = Counter()
    invalid: list[int] = []
    decisions: dict[str, str] = {}
    for index, response in enumerate(responses):
        if not isinstance(response, Mapping):
            invalid.append(index)
            continue
        candidate_id = response.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            invalid.append(index)
            continue
        seen[candidate_id] += 1
        status = response.get("status")
        reason = response.get("reason")
        if (not isinstance(status, str) or status not in DECISION_STATUSES
                or (status != "REQUIREMENT" and
                    (not isinstance(reason, str) or not reason.strip()))):
            invalid.append(index)
            continue
        if candidate_id in expected:
            decisions[candidate_id] = status

    duplicate = tuple(sorted(key for key, count in seen.items() if count > 1))
    unknown = tuple(sorted(set(seen) - expected))
    missing = tuple(sorted(expected - set(seen)))
    # 중복된 응답은 마지막 결과로 덮어쓴 것으로 인정하지 않는다.
    decisions = {key: status for key, status in decisions.items() if seen[key] == 1}

    def with_status(status: str) -> tuple[str, ...]:
        return tuple(sorted(key for key, value in decisions.items() if value == status))

    unresolved = with_status("UNRESOLVED")
    needs_context = with_status("NEEDS_CONTEXT")
    coverage: CoverageStatus
    if invalid or duplicate or unknown:
        coverage = "INVALID"
    elif not items:
        coverage = "EMPTY"
    elif missing or unresolved or needs_context:
        coverage = "INCOMPLETE"
    else:
        coverage = "COMPLETE"
    return CoverageReport(
        coverage_status=coverage, candidate_count=len(items), processed_count=len(decisions),
        candidate_set_sha256=_digest(sorted(ids)),
        requirement_candidate_ids=with_status("REQUIREMENT"),
        non_requirement_candidate_ids=with_status("NOT_REQUIREMENT"),
        unresolved_candidate_ids=unresolved, needs_context_candidate_ids=needs_context,
        missing_candidate_ids=missing, duplicate_candidate_ids=duplicate,
        unknown_candidate_ids=unknown, invalid_response_indexes=tuple(invalid),
    )
