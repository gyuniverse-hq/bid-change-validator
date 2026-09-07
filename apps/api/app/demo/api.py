"""HTTP surface for the demo, as its own app.

Deliberately not mounted on `app.main`. That application owns the real routes and
belongs to Backend; the demo has no database, no migrations and no persistence,
and mounting it there would blur which endpoints are real.

    uvicorn apps.api.app.demo.api:app --reload --port 8100
    http://localhost:8100/docs

Run it alongside the real API and the frontend can build against this shape while
the tables are still being designed. When they land, `services/analysis.py` takes
over and these routes move to `app.main` with the same response model.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..ai.profile import CompanyProfileSnapshot
from .connectors import (
    ChainedNoticeSource,
    CsvIndustryCatalog,
    FileProfileStore,
    FixtureNoticeSource,
    G2BNoticeSource,
    NoticePriceBoard,
)
from .pipeline import EligibilityReport, review_notice


REPO_ROOT = Path(__file__).resolve().parents[4]
STANDARD_INDEX = REPO_ROOT / "data" / "standards" / "clauses.json"
DEMO_RFP_DIR = REPO_ROOT / "data" / "demo" / "rfp"

app = FastAPI(
    title="Bid Change Validator — 적격성 판정 데모",
    version="0.1.0",
    description=(
        "나라장터 공고 + 가상 회사 프로필 → 참가자격 적/부 판정과 계약조항 검토. "
        "DB 연결 전 단계의 데모이며, 회사 프로필은 모두 가상입니다."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_profiles = FileProfileStore()
_fixtures = FixtureNoticeSource()
_industries = CsvIndustryCatalog()
_prices = NoticePriceBoard()


def _notice_source(live: bool):
    if not live:
        return _fixtures
    service_key = os.getenv("G2B_SERVICE_KEY")
    if not service_key:
        raise HTTPException(
            status_code=503,
            detail={"code": "G2B_KEY_MISSING", "message": "G2B_SERVICE_KEY가 설정되지 않았습니다."},
        )
    live_source = G2BNoticeSource(
        service_key=service_key,
        base_url=os.getenv("G2B_BASE_URL")
        or "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
        cache_dir=_fixtures.directory,
    )
    return ChainedNoticeSource(live_source, _fixtures)


def _standard_clauses() -> list[dict[str, Any]] | None:
    if not STANDARD_INDEX.exists():
        return None
    from ..ai.clause_review.standards import load_clauses

    return load_clauses(STANDARD_INDEX)


def _narrator():
    from ..ai.providers import OpenAINarrator

    narrator = OpenAINarrator()
    return narrator if narrator.available else None


def _extractor():
    from ..ai.providers import OpenAIStructuredExtractor

    extractor = OpenAIStructuredExtractor()
    return extractor if extractor.available else None


class ProfileInfo(BaseModel):
    profile_id: str
    company_name: str | None = None
    is_demo: bool = True
    scenario: str | None = None


class ReviewRequest(BaseModel):
    notice_no: str
    profile_id: str | None = None
    # A caller may post a profile instead of naming a stored one, which is what
    # a "가상의 회사 정보를 입력" form on the frontend sends.
    profile: CompanyProfileSnapshot | None = None
    rfp_text: str | None = None
    rfp_fixture: str | None = Field(
        default=None, description="data/demo/rfp 안의 파일명 (rfp_text 대신 사용)"
    )
    live: bool = False
    summarize: bool = False
    extract_requirements: bool = False
    deep_clause_review: bool = False


@app.get("/demo/health", tags=["demo"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "profiles": len(_profiles.list_ids()),
        "notice_fixtures": len(_fixtures.available()),
        "industry_codes": len(_industries),
        "standard_index": STANDARD_INDEX.exists(),
        "llm_available": _extractor() is not None,
    }


@app.get("/demo/profiles", response_model=list[ProfileInfo], tags=["demo"])
def list_profiles() -> list[ProfileInfo]:
    infos = []
    for profile_id in _profiles.list_ids():
        raw = _profiles.raw(profile_id) or {}
        snapshot = _profiles.get(profile_id)
        name = None
        if snapshot and snapshot.basic.company_name:
            name = str(snapshot.basic.company_name.value or "")
        infos.append(
            ProfileInfo(
                profile_id=profile_id,
                company_name=name,
                is_demo=bool(raw.get("_demo")),
                scenario=raw.get("_시나리오") or raw.get("_scenario"),
            )
        )
    return infos


@app.get("/demo/notices", tags=["demo"])
def list_notices() -> dict[str, list[str]]:
    rfps = sorted(path.name for path in DEMO_RFP_DIR.glob("*.txt")) if DEMO_RFP_DIR.exists() else []
    return {"notices": _fixtures.available(), "rfp_fixtures": rfps}


@app.post("/demo/review", response_model=EligibilityReport, tags=["demo"])
def review(request: ReviewRequest) -> EligibilityReport:
    rfp_text = request.rfp_text
    if rfp_text is None and request.rfp_fixture:
        path = DEMO_RFP_DIR / request.rfp_fixture
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail={"code": "RFP_FIXTURE_NOT_FOUND", "message": f"{request.rfp_fixture} 없음"},
            )
        rfp_text = path.read_text(encoding="utf-8")

    report = review_notice(
        request.notice_no,
        notice_source=_notice_source(request.live),
        profile=request.profile,
        profile_id=request.profile_id,
        profile_store=_profiles,
        industry_catalog=_industries,
        price_board=_prices,
        narrate=_narrator() if request.summarize else None,
        rfp_text=rfp_text,
        standard_clauses=_standard_clauses() if rfp_text else None,
        structured_extract=_extractor()
        if (request.extract_requirements or request.deep_clause_review)
        else None,
        use_embedding_fallback=request.deep_clause_review,
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOTICE_NOT_FOUND",
                "message": f"공고 {request.notice_no}를 찾지 못했습니다. live=true 로 조회해 보세요.",
            },
        )
    return report


class AssistRequest(BaseModel):
    """A question asked against a review that has already been produced.

    The report is posted back rather than recomputed so the assistant can only
    ever speak about verdicts code already reached.
    """

    question: str
    report: EligibilityReport
    profile: CompanyProfileSnapshot | None = None
    profile_id: str | None = None


@app.post("/demo/assist", tags=["demo"])
def assist(request: AssistRequest) -> dict[str, str]:
    from ..ai.assist import answer_question, summarize_state

    profile = request.profile
    if profile is None and request.profile_id:
        profile = _profiles.get(request.profile_id)

    state = summarize_state(
        profile=profile,
        judgments=request.report.judgments,
        requirements=request.report.requirements,
        clause_findings=request.report.clause_findings,
        notice_title=request.report.notice.title,
        diagnostics=request.report.diagnostics,
    )
    answer = answer_question(request.question, state_summary=state, narrate=_narrator())
    return {"answer": answer.text, "status": answer.status}


@app.post("/demo/narrate", tags=["demo"])
def narrate(report: EligibilityReport) -> dict[str, str]:
    """Read a produced report back as prose. Never changes a verdict."""
    from ..ai.summary import narrate_report
    from .report import render_report_text

    told = narrate_report(render_report_text(report), narrate=_narrator())
    return {"text": told.text or "", "status": told.status, "notes": told.notes}
