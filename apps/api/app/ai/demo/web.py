"""공고 검토 데모 — 브라우저에서 클릭하며 보는 화면.

    uvicorn apps.api.app.ai.demo.web:app --port 8200
    http://localhost:8200

`app.ai` 의 실제 파이프라인을 HTTP 로 노출만 합니다. **판정은 전부 코드가 합니다** —
참가자격은 `judgment.judge_requirements`, 계약조건은 `clause_review` 가 하고, 이
파일은 그 함수들을 부르기만 합니다. 브라우저는 순수 클라이언트라 판정 로직을 다시
구현하지 않습니다. 두 곳에 같은 로직이 생기면 반드시 어긋나기 때문입니다.

데이터베이스를 쓰지 않습니다. `main.py` 는 Backend 소유라 라우터를 붙이지 않고 별도
앱으로 둡니다. 아무것도 저장하지 않습니다.

LLM 이 없어도 절반은 돌아갑니다. 계약조건 검토는 순수 코드라 키 없이 동작하고,
참가자격 판정만 산문에서 요건을 뽑는 단계에 모델이 필요합니다. 그 경우 화면은
"판정 불가"가 아니라 왜 못 하는지를 말합니다.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..qualification.extraction.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from ..narration.briefing import ChatAnswer, answer_question, build_briefing
from ..narration.business_plan import BusinessPlanDraft, BusinessPlanInputs, generate_business_plan_draft
from ..qualification.extraction.chunking import chunk_source_blocks
from ..clause_review import (
    ClauseFinding,
    detect_patterns,
    detect_standard_diff,
    overlapping_categories,
    scope_for_notice,
)
from ..clause_review.contracts import VERDICT_LABELS
from ..clause_review.standards import SCOPE_LABELS, load_clauses, resolve_all
from ..extensions import describe_required, parse_answer_for
from ...qualification.rules.judgment import CompanyProfileSnapshot, judge_requirements
from ..narration.notice_digest import build_notice_digest


REPO_ROOT = Path(__file__).resolve().parents[5]

# The model providers read `os.environ`, while `Settings` reads `.env` without
# exporting it — so without this a key sitting in `.env` looks like no key at all.
# Done here rather than in the providers because this is an entry point; the
# library must not decide where a process gets its configuration from.
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # python-dotenv is optional; the env may be set already
    pass

STANDARDS_PATH = REPO_ROOT / "data" / "standards" / "clauses.json"
DOCUMENT_CACHE = REPO_ROOT / "data" / "demo" / "notice-documents"
PAGE_PATH = Path(__file__).with_name("web.html")

BUSINESS_TYPE_ORDER = ("SERVICE", "GOODS", "CONSTRUCTION", "FOREIGN", "OTHER")

# 한 화면에서 공고를 오가도 매번 다시 받아오지 않도록 메모리에만 둡니다.
# 저장소가 아니라 창을 닫으면 사라지는 캐시입니다.
_contexts: dict[str, dict[str, Any]] = {}

app = FastAPI(
    title="공고 검토 데모",
    description="참가자격과 계약조건을 코드로 판정하고, 그 근거를 원문까지 펼쳐 봅니다.",
)


# ── 공용 ─────────────────────────────────────────────────────────────────
def _clauses() -> list[dict[str, Any]]:
    """요청마다 다시 읽습니다 — 인덱스를 다시 만들면 재시작 없이 반영됩니다."""
    return load_clauses(STANDARDS_PATH)


def _providers() -> tuple[Any, Any]:
    from ..providers.openai import OpenAINarrator, OpenAIStructuredExtractor

    return OpenAIStructuredExtractor(), OpenAINarrator()


def _finding_json(
    finding: ClauseFinding, findings: list[ClauseFinding] | None = None
) -> dict[str, Any]:
    risk_types, categories = overlapping_categories(finding, findings or [finding])
    standard = finding.standard
    return {
        "risk_type": risk_types[0] if risk_types else None,
        "risk_types": risk_types,
        "category": categories[0] if categories else None,
        # `category` remains the stable grouping value; JSONB `categories` keeps
        # every cause, including the one-element case.
        "categories": categories,
        "label": finding.label,
        "rule_id": finding.rule_id,
        "verdict": finding.verdict,
        "verdict_label": finding.verdict_label,
        "reason": finding.reason,
        "matched_text": finding.matched_text,
        "clause_label": finding.clause_label,
        "chunk_id": finding.chunk_id,
        "excerpt": finding.excerpt,
        "notice_value_raw": finding.notice_value_raw,
        "notice_value": finding.notice_value,
        "standard": None
        if standard is None
        else {
            "clause_ref": standard.clause_ref,
            "description": standard.description,
            "value_raw": standard.value_raw,
            "text_excerpt": standard.text_excerpt,
        },
        "drift": finding.details.get("drift"),
    }


# ── 기준값 ───────────────────────────────────────────────────────────────
@app.get("/api/standards", tags=["기준값"])
def standards() -> dict[str, Any]:
    """계약 종류별 비교 기준. 전부 방금 예규·법령 원문에서 읽은 값입니다."""
    clauses = _clauses()
    scopes = []
    for scope, label in SCOPE_LABELS.items():
        rows = [
            {
                "rule_id": rule_id,
                "status": item["status"],
                "raw": item.get("raw"),
                "value": item.get("value"),
                "ref": item.get("ref"),
                "notes": item.get("notes"),
            }
            for rule_id, item in resolve_all(clauses, contract_scope=scope).items()
        ]
        scopes.append({"scope": scope, "label": label, "rules": rows})
    return {"clause_count": len(clauses), "scopes": scopes}


@app.get("/api/health", tags=["기준값"])
def health() -> dict[str, Any]:
    extractor, narrator = _providers()
    return {
        "llm_available": extractor.available,
        "narrator_available": narrator.available,
        "cached_notices": [
            path.name for path in sorted(DOCUMENT_CACHE.glob("*")) if path.is_dir()
        ],
    }


# ── 문장 검토 ────────────────────────────────────────────────────────────
class TextRequest(BaseModel):
    text: str = Field(min_length=1)
    scope: str = "COMMON"


@app.post("/api/review-text", tags=["검토"])
def review_text(payload: TextRequest) -> dict[str, Any]:
    scope = payload.scope if payload.scope in SCOPE_LABELS else "COMMON"
    chunks = [{"chunk_id": "CHUNK-0000", "clause_label": None, "text": payload.text}]
    findings = detect_standard_diff(chunks, _clauses(), contract_scope=scope)
    findings += detect_patterns(chunks)
    counts = {name: 0 for name in VERDICT_LABELS}
    for finding in findings:
        counts[finding.verdict] += 1
    return {
        "contract_scope": scope,
        "scope_label": SCOPE_LABELS[scope],
        "counts": counts,
        "risk_types": list(
            dict.fromkeys(
                finding.risk_type_code
                for finding in findings
                if finding.risk_type_code is not None
            )
        ),
        "findings": [_finding_json(finding, findings) for finding in findings],
    }


# ── 공고 불러오기 ────────────────────────────────────────────────────────
class NoticeRequest(BaseModel):
    notice_no: str = Field(min_length=1)
    refresh: bool = False


def _lookup_notice(notice_no: str) -> tuple[dict[str, Any], str] | None:
    """나라장터 조회. 업무구분별로 엔드포인트가 달라 차례로 물어봅니다.

    함수 안에서 import 합니다 — 클라이언트가 네트워크와 설정을 건드리는데
    `app.ai` 는 둘 다 하지 않는 라이브러리로 남아야 합니다.
    """
    from ...config import get_settings
    from ...schemas import BusinessType, NoticeInquiryType
    from ...services.g2b import G2BApiError, G2BClient

    settings = get_settings()
    service_key = settings.decoded_g2b_service_key
    if not service_key:
        return None

    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    for name in BUSINESS_TYPE_ORDER:
        try:
            page = client.fetch_page(
                business_type=BusinessType(name),
                inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                page_number=1,
                page_size=10,
                bid_notice_no=notice_no,
            )
        except G2BApiError:
            continue
        if page.items:
            return page.items[0], name
    return None


def _extract_requirements(
    chunks: list[dict[str, Any]], notice_no: str
) -> tuple[Any, str]:
    """공고 산문에서 참가자격 요건을 구조화합니다. 여기서만 모델을 씁니다."""
    extractor, _ = _providers()
    if not extractor.available:
        return None, "OPENAI_API_KEY 가 없어 참가자격 요건을 뽑지 못했습니다."

    documents = [
        QualificationDocumentInput(
            document_id="DEMO-DOC",
            extracted_blocks=[
                {"block_index": index, "text": chunk["text"]}
                for index, chunk in enumerate(chunks)
            ],
        )
    ]
    try:
        analysis = analyze_qualification_documents(
            QualificationAnalysisInput(
                notice_id=notice_no,
                notice_version_id=notice_no,
                documents=documents,
            ),
            structured_extract=extractor,
        )
    except Exception as error:  # noqa: BLE001 — 추출 실패가 조항검토를 막지는 않는다
        return None, f"요건 추출에 실패했습니다: {type(error).__name__}"

    if not analysis.requirements:
        return analysis, (
            "이 공고 문서에서 판정할 수 있는 참가자격 요건을 찾지 못했습니다. "
            "자격이 목록 API 쪽에만 적혀 있거나, 첨부가 규격서뿐인 경우 흔합니다."
        )
    return analysis, ""


@app.post("/api/notice", tags=["공고"])
def load_notice(payload: NoticeRequest) -> dict[str, Any]:
    """공고를 받아 계약조건 검토·요건 추출·요약까지 한 번에 준비합니다."""
    from .documents import G2BDocumentSource

    notice_no = payload.notice_no.strip()
    if not payload.refresh and notice_no in _contexts:
        return _context_json(_contexts[notice_no])

    found = _lookup_notice(notice_no)
    if found is None:
        return {
            "error": "NOTICE_NOT_FOUND",
            "message": (
                "해당 공고번호를 찾지 못했습니다. 하이픈 없이 넣어주세요 "
                "(예: R26BK01705963). G2B_SERVICE_KEY 설정도 확인해 주세요."
            ),
        }

    item, business_type = found
    documents: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for document in G2BDocumentSource(cache_dir=DOCUMENT_CACHE).fetch(item):
        documents.append(
            {
                "filename": document.filename,
                "bytes": document.size_bytes,
                "blocks": len(document.blocks),
                "error": document.error,
            }
        )
        blocks.extend(document.blocks)

    notice = {
        "notice_no": notice_no,
        "name": item.get("bidNtceNm"),
        "institution": item.get("ntceInsttNm"),
        "demand_institution": item.get("dminsttNm"),
        "deadline": item.get("bidClseDt"),
        "price": item.get("presmptPrce") or item.get("asignBdgtAmt"),
        "detail_url": item.get("bidNtceDtlUrl"),
        "business_type": business_type,
    }
    if not blocks:
        return {
            "error": "NO_READABLE_DOCUMENT",
            "message": "첨부 문서에서 텍스트를 읽지 못했습니다.",
            "notice": notice,
            "documents": documents,
        }

    chunks = [
        {**chunk, "chunk_id": f"CHUNK-{index:04d}"}
        for index, chunk in enumerate(chunk_source_blocks(blocks))
    ]
    scope = scope_for_notice(chunks, business_type=business_type)

    findings = detect_standard_diff(chunks, _clauses(), contract_scope=scope)
    findings += detect_patterns(chunks)

    analysis, extraction_note = _extract_requirements(chunks, notice_no)

    digest = None
    extractor, narrator = _providers()
    if narrator.available:
        try:
            digest = build_notice_digest(
                chunks,
                title=notice["name"],
                notice_id=notice_no,
                notice_version_id=notice_no,
                narrate=narrator,
                structured_extract=extractor if extractor.available else None,
            )
        except Exception:  # noqa: BLE001 — 요약 실패가 검토를 막지는 않는다
            digest = None

    context = {
        "context_id": notice_no,
        "notice": notice,
        "documents": documents,
        "chunks": chunks,
        "scope": scope,
        "findings": findings,
        "analysis": analysis,
        "extraction_note": extraction_note,
        "digest": digest,
    }
    _contexts[notice_no] = context
    return _context_json(context)


def _context_json(context: dict[str, Any]) -> dict[str, Any]:
    analysis = context["analysis"]
    findings: list[ClauseFinding] = context["findings"]
    counts = {name: 0 for name in VERDICT_LABELS}
    for finding in findings:
        counts[finding.verdict] += 1

    digest = context.get("digest")
    requirements = list(analysis.requirements) if analysis else []
    return {
        "context_id": context["context_id"],
        "notice": context["notice"],
        "documents": context["documents"],
        "chunk_count": len(context["chunks"]),
        "char_count": sum(len(chunk["text"]) for chunk in context["chunks"]),
        "contract_scope": context["scope"],
        "scope_label": SCOPE_LABELS[context["scope"]],
        "counts": counts,
        "risk_types": list(
            dict.fromkeys(
                finding.risk_type_code
                for finding in findings
                if finding.risk_type_code is not None
            )
        ),
        "findings": [_finding_json(finding, findings) for finding in findings],
        "requirement_count": len(requirements),
        "extraction_note": context["extraction_note"],
        "summary": None if digest is None else digest.overview.text,
        "summary_available": bool(digest and digest.overview.available),
        "sections": []
        if digest is None
        else [
            {
                "topic": section.topic,
                "label": section.label,
                "summary": section.summary,
                "chunk_ids": section.chunk_ids,
            }
            for section in digest.sections.sections
        ],
        # 프로필을 채우기 전에도 "이 공고가 무엇을 요구하는지"는 보이게 한다.
        "requirements": [
            {
                "requirement_key": item.requirement_key,
                "type": item.type,
                "raw": item.raw,
            }
            for item in requirements
        ],
        "extensions": describe_required(requirements),
    }


# ── 참가자격 판정 ────────────────────────────────────────────────────────
class JudgeRequest(BaseModel):
    context_id: str
    profile: dict[str, Any]


def _profile_from_payload(payload: dict[str, Any]) -> CompanyProfileSnapshot:
    """Validate core fields and parse notice-specific answers without a model."""
    data = {"company_id": "DEMO-COMPANY", **payload}
    answers = data.get("extensions") or {}
    if isinstance(answers, dict):
        data["extensions"] = {
            key: parse_answer_for(key, value) if isinstance(value, str) else value
            for key, value in answers.items()
        }
    return CompanyProfileSnapshot.model_validate(data)


def _chunk_text(context: dict[str, Any], chunk_id: str | None) -> str | None:
    if not chunk_id:
        return None
    for chunk in context["chunks"]:
        if chunk["chunk_id"] == chunk_id:
            return chunk["text"]
    return None


def _evidence_json(context: dict[str, Any], quote: Any) -> dict[str, Any]:
    return {
        "quote": quote.quote,
        "location": quote.location,
        "chunk_id": quote.chunk_id,
        # 펼쳤을 때 앞뒤 맥락까지 보이도록 원문 단락을 통째로 싣는다.
        "source_text": _chunk_text(context, quote.chunk_id),
    }


@app.post("/api/judge", tags=["판정"])
def judge(payload: JudgeRequest) -> dict[str, Any]:
    """프로필과 요건을 대조합니다. 코드가 판정하고 모델은 개입하지 않습니다.

    각 판정에는 근거가 두 겹으로 붙습니다: 공고에서 뽑아낸 요건 문장(요약)과, 그
    문장이 실제로 있던 원문 단락(발췌). 담당자가 판정을 믿지 못할 때 그 자리에서
    원문까지 펼쳐볼 수 있어야 하기 때문입니다.
    """
    context = _contexts.get(payload.context_id)
    if context is None:
        return {"error": "CONTEXT_NOT_FOUND", "message": "공고를 먼저 불러오세요."}

    analysis = context["analysis"]
    if analysis is None or not analysis.requirements:
        return {
            "error": "NO_REQUIREMENTS",
            "message": context["extraction_note"]
            or "이 공고에서 판정할 참가자격 요건을 찾지 못했습니다.",
            "judgments": [],
        }

    try:
        profile = _profile_from_payload(payload.profile)
    except Exception as error:  # noqa: BLE001
        return {"error": "INVALID_PROFILE", "message": f"프로필 형식 오류: {error}"}

    evaluation = judge_requirements(
        list(analysis.requirements),
        profile,
        preflight_case_id=str(uuid.uuid4()),
        reference_date=date.today(),
    )
    briefing = build_briefing(
        judgments=evaluation.judgments,
        requirements=list(analysis.requirements),
        evidence=list(analysis.evidence),
        diagnostics=list(analysis.diagnostics),
        clause_findings=context["findings"],
        overall_status=evaluation.overall_status,
        notice_id=context["context_id"],
        title=context["notice"]["name"],
    )

    return {
        "context_id": context["context_id"],
        "overall_status": briefing.overall_status,
        "overall_label": briefing.overall_label,
        "counts": briefing.counts(),
        "judgments": [
            {
                "requirement_key": item.requirement_key,
                "type": item.requirement_type,
                "status": item.status,
                "status_label": item.status_label,
                "reason": item.reason,
                "basis": item.basis,
                "requires_evidence": item.requires_evidence,
                # 근거 1층 — 공고에서 뽑아낸 요건 문장
                "requirement_raw": item.requirement_raw,
                "profile_refs": item.profile_refs,
                # 근거 2층 — 그 문장이 있던 원문
                "evidence": [_evidence_json(context, q) for q in item.evidence],
            }
            for item in briefing.judgments
        ],
        "notice_facts": [
            {
                "code": fact.code,
                "message": fact.message,
                "raw": fact.raw,
                "evidence": [_evidence_json(context, q) for q in fact.evidence],
            }
            for fact in briefing.notice_facts
        ],
    }


# ── 도우미 ───────────────────────────────────────────────────────────────
class AssistRequest(BaseModel):
    context_id: str
    question: str = Field(min_length=1)
    profile: dict[str, Any] | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


class BusinessPlanRequest(BaseModel):
    context_id: str
    profile: dict[str, Any]
    inputs: BusinessPlanInputs


def _build_context_briefing(
    context: dict[str, Any], profile: CompanyProfileSnapshot
) -> Any:
    """Build the same settled context used by judgment, chat and draft writing."""
    analysis = context["analysis"]
    evaluation = judge_requirements(
        list(analysis.requirements),
        profile,
        preflight_case_id=str(uuid.uuid4()),
        reference_date=date.today(),
    )
    return build_briefing(
        judgments=evaluation.judgments,
        requirements=list(analysis.requirements),
        evidence=list(analysis.evidence),
        diagnostics=list(analysis.diagnostics),
        clause_findings=context["findings"],
        digest=context.get("digest"),
        overall_status=evaluation.overall_status,
        notice_id=context["context_id"],
        title=context["notice"]["name"],
    )


@app.post("/api/business-plan-draft", tags=["사업계획서"])
def business_plan_draft(payload: BusinessPlanRequest) -> BusinessPlanDraft:
    """Create a review-required draft from settled results and user facts."""
    context = _contexts.get(payload.context_id)
    if context is None:
        return BusinessPlanDraft(
            text="공고를 먼저 불러오세요.",
            status="FAILED",
            notice_id=payload.context_id,
        )
    analysis = context["analysis"]
    if analysis is None or not analysis.requirements:
        return BusinessPlanDraft(
            text=context["extraction_note"] or "판정할 참가자격 요건이 없습니다.",
            status="FAILED",
            notice_id=context["context_id"],
        )
    try:
        profile = _profile_from_payload(payload.profile)
    except Exception as error:  # noqa: BLE001
        return BusinessPlanDraft(
            text=f"프로필 형식 오류: {error}",
            status="FAILED",
            notice_id=context["context_id"],
        )

    briefing = _build_context_briefing(context, profile)
    _, narrator = _providers()
    return generate_business_plan_draft(
        briefing,
        payload.inputs,
        narrate=narrator if narrator.available else None,
    )


@app.post("/api/assist", tags=["도우미"])
def assist(payload: AssistRequest) -> ChatAnswer:
    """확정된 판정과 원문 인용만 보고 답합니다. 새로 판정하지 않습니다."""
    context = _contexts.get(payload.context_id)
    if context is None:
        return ChatAnswer(text="공고를 먼저 불러오세요.", status="FAILED")

    analysis = context["analysis"]
    judgments: list[Any] = []
    if analysis is not None and analysis.requirements and payload.profile is not None:
        try:
            profile = _profile_from_payload(payload.profile)
            judgments = judge_requirements(
                list(analysis.requirements),
                profile,
                preflight_case_id=str(uuid.uuid4()),
                reference_date=date.today(),
            ).judgments
        except Exception:  # noqa: BLE001 — 판정이 없어도 조항 질문에는 답할 수 있다
            judgments = []

    briefing = build_briefing(
        judgments=judgments,
        requirements=list(analysis.requirements) if analysis else [],
        evidence=list(analysis.evidence) if analysis else [],
        diagnostics=list(analysis.diagnostics) if analysis else [],
        clause_findings=context["findings"],
        digest=context.get("digest"),
        notice_id=context["context_id"],
        title=context["notice"]["name"],
    )
    _, narrator = _providers()
    return answer_question(
        payload.question,
        briefing,
        narrate=narrator if narrator.available else None,
        history=[(turn.get("q", ""), turn.get("a", "")) for turn in payload.history],
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def page() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")
