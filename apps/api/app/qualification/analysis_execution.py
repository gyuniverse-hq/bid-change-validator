"""분석 실행의 경로·원문 기준을 기록한다. 모델 출력이나 회사 정보는 복사하지 않는다."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..ai.qualification.extraction.review_execution import ReviewOptions
from .state_contract import payload_fingerprint

EXECUTION_CODE = "QUALIFICATION_EXTRACTION_BASIS"
EXECUTION_VERSION = "qualification-extraction-basis-v1"
SUPPORTED_STRATEGIES = ("legacy", "review_v1")


def product_review_options() -> ReviewOptions:
    """클라이언트가 호출 예산을 늘릴 수 없도록 제품 경계에서 고정한다.

    elapsed는 호출 사이에 검사하는 예산이다. 단일 HTTP 제한과 전체 wall-clock은 다르다.
    """
    return ReviewOptions(max_retries=1, max_calls=24, max_elapsed_seconds=180)


def source_basis(version, analysis_input) -> dict[str, Any]:
    """누락 첨부까지 지문에 포함한다. blocks 순서는 의미가 있으므로 정렬하지 않는다."""
    data = analysis_input.model_dump(mode="json")
    data["documents"] = sorted(data["documents"], key=lambda item: item["document_id"])
    used = {item["document_id"] for item in data["documents"]}
    documents = [{"document_id": str(doc.id), "extraction_status": doc.extraction_status,
                  "file_sha256": doc.file_sha256, "text_sha256": doc.extracted_text_sha256,
                  "included": str(doc.id) in used}
                 for doc in sorted(version.documents, key=lambda item: str(item.id))]
    return {"source_sha256": payload_fingerprint({"input": data, "documents": documents}),
            "input_sha256": payload_fingerprint(data),
            "document_count": len(documents), "included_document_count": len(used),
            "omitted_document_ids": [item["document_id"] for item in documents if not item["included"]]}


def execution_metadata(diagnostics) -> dict[str, Any] | None:
    """과거 결과는 출처 없는 경로를 추측하지 않는다. 중복/파손된 기록도 미확인으로 둔다."""
    rows = [item.get("details") for item in (diagnostics or [])
            if isinstance(item, Mapping) and item.get("code") == EXECUTION_CODE]
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    result = dict(rows[0])
    if result.get("version") != EXECUTION_VERSION or result.get("strategy") not in SUPPORTED_STRATEGIES:
        return None
    for key in ("input_sha256", "source_sha256"):
        value = result.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            return None
    return result
