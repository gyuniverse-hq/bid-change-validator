"""저장된 분석·판정 결과를 브리핑으로 조립하는 서비스 계층.

LLM/RAG 쪽에서 만든 요약·브리핑·챗봇을 HTTP 로 꺼내기 위한 배관이다. 팀 컨벤션을
따라 서비스(이 파일)와 라우터(`qualification_briefing_router.py`)를 나눴다.

**다른 분 영역은 읽기만 한다.** `analysis_models` · `judgment_models` · `models` ·
`database` · `qualification_analysis` · `qualification_judgment` 를 import 해서 쓰지만
수정하지 않았고, 새 테이블도 마이그레이션도 없다. 이미 저장된 값만 읽어 조립한다.

`main.py` 에도 등록하지 않았다 — 라우터를 붙이려면 그 파일에 한 줄이 필요한데
그건 Backend 소유라서, 준비만 해두고 등록은 팀에 요청한다
(docs/llm-rag/02-integration-requests.md 참조).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .ai.narration.briefing import (
    ChatAnswer,
    NoticeBriefing,
    answer_question,
    build_briefing,
    narrate_briefing,
)
from .ai.clause_review import detect_patterns, detect_standard_diff
from .ai.contracts import Evidence, EvidenceLocation, Judgment, QualificationRequirement
from .ai.narration.notice_digest import NoticeDigest, build_notice_digest
from .ai.providers.openai import OpenAINarrator, OpenAIStructuredExtractor
from .ai.narration.summary import NoticeSummary
from .analysis_models import QualificationAnalysisRun
from .judgment_models import QualificationJudgmentRun
from .models import BidNotice, BidNoticeVersion
from .qualification_analysis import build_qualification_analysis_input


STANDARD_CLAUSES_PATH = "data/standards/clauses.json"


class QualificationBriefingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ── DB 레코드 → app.ai 계약 ──────────────────────────────────────────────
#
# 저장 모델과 AI 계약이 같은 모양이 아니다. 저장 쪽은 컬럼 이름과 JSONB 를 쓰고
# AI 쪽은 pydantic 계약을 쓴다. 변환을 한곳에 모아두면 어느 한쪽이 바뀌어도
# 고칠 자리가 하나다.


def _to_requirement(record: Any) -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key=record.requirement_key,
        requirement_group_key=record.requirement_group_key,
        group_operator=record.group_operator,
        notice_version_id=str(record.analysis_run.notice_version_id),
        type=record.type,
        operator=record.operator,
        value=record.value_json,
        unit=record.unit,
        period_months=float(record.period_months) if record.period_months is not None else None,
        scope=dict(record.scope or {}),
        required=record.required,
        raw=record.raw,
        confidence=float(record.confidence) if record.confidence is not None else None,
        evidence_keys=list(record.evidence_keys or []),
    )


def _to_evidence(record: Any) -> Evidence:
    return Evidence(
        evidence_key=record.evidence_key,
        source_type=record.source_type,
        document_id=record.document_id,
        notice_version_id=record.notice_version_id,
        case_id=record.case_id,
        chunk_id=record.chunk_id,
        location=EvidenceLocation(**(record.location or {})),
        quote=record.quote,
        source_sha256=record.source_sha256,
        extracted_text_sha256=record.extracted_text_sha256,
    )


def _to_judgment(record: Any, run: QualificationJudgmentRun) -> Judgment:
    return Judgment(
        judgment_key=record.judgment_key,
        preflight_case_id=str(run.preflight_case_id),
        notice_version_id=str(run.notice_version_id),
        requirement_key=record.requirement_key,
        status=record.status,
        basis_type=record.basis_type,
        evidence_held=record.evidence_held,
        reason_code=record.reason_code,
        requires_evidence=record.requires_evidence,
        profile_refs=list(record.profile_refs or []),
        requirement_evidence_keys=list(record.requirement_evidence_keys or []),
        rule_version=record.rule_version,
    )


def _to_diagnostics(run: QualificationAnalysisRun) -> list[Any]:
    from .ai.extraction.analysis_result import AnalysisDiagnostic

    parsed: list[AnalysisDiagnostic] = []
    for item in run.diagnostics or []:
        try:
            parsed.append(AnalysisDiagnostic.model_validate(item))
        except Exception:  # noqa: BLE001 - 옛 형식 진단은 건너뛴다
            continue
    return parsed


# ── 로더 ─────────────────────────────────────────────────────────────────
def _load_notice_version(
    db: Session, notice_id: UUID, version_number: int
) -> BidNoticeVersion:
    version = db.scalar(
        select(BidNoticeVersion)
        .options(selectinload(BidNoticeVersion.documents))
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
        )
    )
    if version is None:
        raise QualificationBriefingError(
            "NOTICE_VERSION_NOT_FOUND", "해당 공고 버전을 찾을 수 없습니다."
        )
    return version


def _load_judgment_run(db: Session, run_id: UUID) -> QualificationJudgmentRun:
    run = db.scalar(
        select(QualificationJudgmentRun)
        .options(
            selectinload(QualificationJudgmentRun.judgments),
            selectinload(QualificationJudgmentRun.analysis_run).selectinload(
                QualificationAnalysisRun.requirements
            ),
            selectinload(QualificationJudgmentRun.analysis_run).selectinload(
                QualificationAnalysisRun.evidence
            ),
        )
        .where(QualificationJudgmentRun.id == run_id)
    )
    if run is None:
        raise QualificationBriefingError(
            "JUDGMENT_RUN_NOT_FOUND", "해당 판정 실행을 찾을 수 없습니다."
        )
    return run


def _notice_title(db: Session, version: BidNoticeVersion) -> str | None:
    notice = db.get(BidNotice, version.notice_id)
    return getattr(notice, "title", None) if notice else None


def _chunks_for_version(version: BidNoticeVersion) -> list[dict[str, Any]]:
    """저장된 추출 블록에서 청크를 만든다. 청크는 저장되지 않아 매번 새로 만든다."""
    from .ai.extraction.backend_blocks import canonical_source_blocks
    from .ai.chunking import chunk_source_blocks

    analysis_input = build_qualification_analysis_input(version)
    chunks: list[dict[str, Any]] = []
    for document in analysis_input.documents:
        canonical = canonical_source_blocks(
            document_id=document.document_id,
            blocks=document.extracted_blocks,
            file_sha256=document.file_sha256,
            text_sha256=document.extracted_text_sha256,
        )
        for chunk in chunk_source_blocks(canonical):
            chunks.append({**chunk, "chunk_id": f"CHUNK-{len(chunks):04d}"})
    return chunks


def _load_standard_clauses() -> list[dict[str, Any]] | None:
    """예규 조문 인덱스. 없으면 조항 검토를 건너뛴다 — 기준 없이 판정하지 않는다."""
    from pathlib import Path

    from .ai.clause_review.standards import load_clauses

    path = Path(STANDARD_CLAUSES_PATH)
    if not path.exists():
        return None
    try:
        return load_clauses(path)
    except (FileNotFoundError, ValueError):
        return None


# ── 공개 진입점 ──────────────────────────────────────────────────────────
def build_notice_digest_for_version(
    db: Session, *, notice_id: UUID, version_number: int
) -> NoticeDigest:
    """공고 전체 요약 + 주제별 세부 요약."""
    version = _load_notice_version(db, notice_id, version_number)
    chunks = _chunks_for_version(version)
    if not chunks:
        raise QualificationBriefingError(
            "NO_EXTRACTED_DOCUMENT",
            "텍스트가 추출된 공고 문서가 없습니다. 문서 추출을 먼저 실행하세요.",
        )

    narrator = OpenAINarrator()
    extractor = OpenAIStructuredExtractor()
    return build_notice_digest(
        chunks,
        title=_notice_title(db, version),
        notice_id=str(notice_id),
        notice_version_id=str(version.id),
        narrate=narrator if narrator.available else None,
        structured_extract=extractor if extractor.available else None,
    )


def build_briefing_for_judgment_run(
    db: Session,
    run_id: UUID,
    *,
    include_digest: bool = True,
    include_clause_review: bool = True,
) -> NoticeBriefing:
    """판정 실행 하나를 판정·근거·요약·조항검토가 붙은 브리핑으로 조립한다."""
    run = _load_judgment_run(db, run_id)
    analysis = run.analysis_run

    version = db.get(BidNoticeVersion, run.notice_version_id)
    title = _notice_title(db, version) if version else None

    digest: NoticeDigest | None = None
    clause_findings: list[Any] = []
    if version is not None and (include_digest or include_clause_review):
        chunks = _chunks_for_version(version)
        if chunks and include_digest:
            narrator = OpenAINarrator()
            extractor = OpenAIStructuredExtractor()
            digest = build_notice_digest(
                chunks,
                title=title,
                notice_id=str(version.notice_id),
                notice_version_id=str(version.id),
                narrate=narrator if narrator.available else None,
                structured_extract=extractor if extractor.available else None,
            )
        if chunks and include_clause_review:
            standards = _load_standard_clauses()
            if standards:
                clause_findings.extend(
                    detect_standard_diff(
                        chunks, standards, notice_version_id=str(version.id)
                    )
                )
            clause_findings.extend(
                detect_patterns(chunks, notice_version_id=str(version.id))
            )

    return build_briefing(
        judgments=[_to_judgment(record, run) for record in run.judgments],
        requirements=[_to_requirement(record) for record in analysis.requirements],
        evidence=[_to_evidence(record) for record in analysis.evidence],
        diagnostics=_to_diagnostics(analysis),
        clause_findings=clause_findings,
        digest=digest,
        overall_status=run.overall_status,
        notice_id=str(version.notice_id) if version else None,
        notice_version_id=str(run.notice_version_id),
        title=title,
    )


def narrate_briefing_for_judgment_run(
    db: Session, run_id: UUID, *, briefing: NoticeBriefing | None = None
) -> NoticeSummary:
    """브리핑을 구두 설명하듯 풀어쓴다. 판정은 바꾸지 않는다."""
    briefing = briefing or build_briefing_for_judgment_run(db, run_id)
    narrator = OpenAINarrator()
    return narrate_briefing(briefing, narrate=narrator if narrator.available else None)


def answer_for_judgment_run(
    db: Session,
    run_id: UUID,
    *,
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> ChatAnswer:
    """확정된 판정 결과를 근거로 담당자 질문에 답한다."""
    briefing = build_briefing_for_judgment_run(db, run_id)
    narrator = OpenAINarrator()
    return answer_question(
        question,
        briefing,
        narrate=narrator if narrator.available else None,
        history=history,
    )
