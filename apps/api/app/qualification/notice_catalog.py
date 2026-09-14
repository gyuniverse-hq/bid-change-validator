"""회사별 저장 판정 카탈로그. 같은 검색 범위에서 상태/유형을 집계한 뒤 페이지를 나눈다.

LLM/규칙 재판정/쓰기 없음. 상태 판정은 5단계와 같은 순수 선택 함수를 사용한다.
대상 전체의 메타데이터를 일괄 읽으며 상위 100건 또는 건별 상태 요청으로 근사하지 않는다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..analysis_models import QualificationAnalysisRun, QualificationEvidenceRecord, QualificationRequirementRecord
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRun
from ..models import BidNotice, BidNoticeVersion, PreflightCase
from .judgment import _load_company, _record_to_completeness, build_company_profile_snapshot
from .rules.judgment import RULE_VERSION
from .state_contract import (QualificationState, ReviewScope, StateInputError, payload_fingerprint,
                             select_qualification_state)
from .state_service import _analysis_snapshot, _judgment_snapshot

CATALOG_VERSION = "qualification-catalog-v1"
BUCKETS = ("eligible", "insufficient_data", "ineligible", "unreviewed")
BUSINESS_TYPES = ("SERVICE", "GOODS", "CONSTRUCTION", "FOREIGN")
# 상한을 넘으면 전체라고 속이지 않고 검색 범위를 좁히도록 오류를 반환한다.
MAX_SCOPE_ROWS = 10_000


def state_bucket(state: QualificationState | None, *, invalid: bool = False) -> str:
    if invalid:
        return "insufficient_data"
    if state is None or state.display_state == "UNREVIEWED":
        return "unreviewed"
    if (state.lookup_state == "OK" and state.display_state == "RESULT_AVAILABLE"
            and state.selected_judgment_run_id and state.stored_overall_status in BUCKETS[:3]):
        return state.stored_overall_status
    return "insufficient_data"


def _latest(model, partitions, filters=()):
    return select(model.id.label("id"), func.row_number().over(
        partition_by=partitions, order_by=(model.created_at.desc(), model.id.desc()),
    ).label("rank")).where(*filters).subquery()


def _analyses(db, version_ids):
    if not version_ids:
        return {}
    ranked = _latest(QualificationAnalysisRun, QualificationAnalysisRun.notice_version_id,
                     (QualificationAnalysisRun.notice_version_id.in_(version_ids),))
    rows = db.scalars(select(QualificationAnalysisRun)
        .join(ranked, ranked.c.id == QualificationAnalysisRun.id).where(ranked.c.rank == 1)
        .options(selectinload(QualificationAnalysisRun.requirements).load_only(
            QualificationRequirementRecord.requirement_key, QualificationRequirementRecord.evidence_keys),
            selectinload(QualificationAnalysisRun.evidence).load_only(
                QualificationEvidenceRecord.evidence_key, QualificationEvidenceRecord.notice_version_id))).all()
    return {row.notice_version_id: row for row in rows}


def _judgments(db, cases, analyses):
    if not cases:
        return {}, {}
    case_ids = [case.id for case in cases.values()]
    owned = (QualificationJudgmentRun.preflight_case_id.in_(case_ids),
             QualificationJudgmentRun.company_id == next(iter(cases.values())).company_id)
    history_rank = _latest(QualificationJudgmentRun, QualificationJudgmentRun.preflight_case_id, owned)
    # 최신 공고 차수/분석/규칙을 만족하는 판정만 후보로 만든다.
    current = {}
    if analyses:
        latest_analysis = _latest(QualificationAnalysisRun, QualificationAnalysisRun.notice_version_id,
                                  (QualificationAnalysisRun.notice_version_id.in_(list(cases)),))
        ranked = (select(QualificationJudgmentRun.id.label("id"), func.row_number().over(
            partition_by=QualificationJudgmentRun.preflight_case_id,
            order_by=(QualificationJudgmentRun.created_at.desc(), QualificationJudgmentRun.id.desc()),
        ).label("rank"))
            .join(PreflightCase, PreflightCase.id == QualificationJudgmentRun.preflight_case_id)
            .join(QualificationAnalysisRun, QualificationAnalysisRun.id == QualificationJudgmentRun.analysis_run_id)
            .join(latest_analysis, latest_analysis.c.id == QualificationAnalysisRun.id)
            .where(*owned, latest_analysis.c.rank == 1,
                   QualificationAnalysisRun.notice_version_id == PreflightCase.current_version_id,
                   QualificationJudgmentRun.notice_version_id == PreflightCase.current_version_id,
                   QualificationJudgmentRun.rule_version == RULE_VERSION).subquery())
        rows = db.scalars(select(QualificationJudgmentRun)
            .join(ranked, ranked.c.id == QualificationJudgmentRun.id).where(ranked.c.rank == 1)
            .options(selectinload(QualificationJudgmentRun.judgments))).all()
        current = {row.preflight_case_id: row for row in rows}
    missing = set(case_ids) - set(current)
    historical = {}
    if missing:
        rows = db.scalars(select(QualificationJudgmentRun)
            .join(history_rank, history_rank.c.id == QualificationJudgmentRun.id)
            .where(history_rank.c.rank == 1, QualificationJudgmentRun.preflight_case_id.in_(missing))
            .options(selectinload(QualificationJudgmentRun.judgments))).all()
        historical = {row.preflight_case_id: row for row in rows}
    return current, historical


def read_notice_catalog(db: Session, *, company_id: UUID | None = None, q: str = "",
                        business_type: str | None = None, status: str | None = None,
                        limit: int = 20, offset: int = 0, reference_date: date | None = None) -> dict[str, Any]:
    """권한은 라우터가 먼저 확인한다. 한 회사·동일 검색 범위의 저장 상태만 반환한다.

    business_counts는 q 범위, status_counts는 q+business_type 범위다.
    상태 필터는 페이지를 자르기 전에 적용한다. 출력은 저장 판정이지 참가 보증이 아니다.
    """
    if not isinstance(q, str) or len(q) > 200:
        raise ValueError("INVALID_CATALOG_QUERY")
    if business_type is not None and business_type not in BUSINESS_TYPES:
        raise ValueError("INVALID_BUSINESS_TYPE")
    if status is not None and status not in BUCKETS:
        raise ValueError("INVALID_STATUS_FILTER")
    if (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100
            or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0):
        raise ValueError("INVALID_CATALOG_PAGE")
    if reference_date is not None and (not isinstance(reference_date, date) or isinstance(reference_date, datetime)):
        raise ValueError("INVALID_REFERENCE_DATE")
    query = q.strip()
    filters = []
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(or_(*(field.ilike(pattern, escape="\\") for field in (
            BidNotice.bid_notice_no, BidNotice.title,
            BidNotice.announcing_institution_name, BidNotice.demanding_institution_name))))
    with db.no_autoflush:
        # 현재 차수 없는 행은 목록과 집계 양쪽에서 동일하게 제외한다.
        rows = db.execute(select(BidNotice, BidNoticeVersion)
            .join(BidNoticeVersion, (BidNoticeVersion.notice_id == BidNotice.id)
                  & BidNoticeVersion.is_current.is_(True)).where(*filters)
            .order_by(BidNotice.last_seen_at.desc(), BidNotice.id.desc())
            .limit(MAX_SCOPE_ROWS + 1)).all()
        if len(rows) > MAX_SCOPE_ROWS:
            raise StateInputError("CATALOG_SCOPE_TOO_LARGE")
        if len({notice.id for notice, _ in rows}) != len(rows):
            raise StateInputError("MULTIPLE_CURRENT_NOTICE_VERSIONS")
        business_counts = dict(Counter(notice.business_type for notice, _ in rows))
        query_total = len(rows)
        rows = [(notice, version) for notice, version in rows
                if business_type is None or notice.business_type == business_type]
        version_ids = [version.id for _, version in rows]
        cases = {}
        profile_hash = None
        if company_id is not None:
            # 잘못된/없는 회사도 빈 카탈로그로 숨기지 않는다.
            company = _load_company(db, company_id)
            completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company_id))
            profile_hash = payload_fingerprint(build_company_profile_snapshot(company, completeness).model_dump(mode="json"))
            if version_ids:
                ranked = _latest(PreflightCase, (PreflightCase.notice_id, PreflightCase.current_version_id),
                    (PreflightCase.company_id == company_id, PreflightCase.current_version_id.in_(version_ids)))
                found = db.scalars(select(PreflightCase).join(ranked, ranked.c.id == PreflightCase.id)
                                  .where(ranked.c.rank == 1)).all()
                cases = {case.current_version_id: case for case in found}
        analyses = _analyses(db, list(cases))
        original_basis = {(vid, run.id, run.status) for vid, run in analyses.items()}
        current, historical = _judgments(db, cases, analyses)
        result = []
        for notice, version in rows:
            case, state, error_code = cases.get(version.id), None, None
            if case is not None:
                scope = ReviewScope(str(case.id), str(notice.id), str(version.id), str(company_id), RULE_VERSION)
                analysis = analyses.get(version.id)
                selected = current.get(case.id) or historical.get(case.id)
                try:
                    if case.notice_id != notice.id:
                        raise StateInputError("CASE_NOTICE_MISMATCH")
                    state = select_qualification_state(scope,
                        [_analysis_snapshot(analysis)] if analysis else [],
                        [_judgment_snapshot(selected, analysis)] if selected else [],
                        current_profile_sha256=profile_hash, reference_date=reference_date)
                except StateInputError:
                    error_code = "QUALIFICATION_STATE_INVALID"
                    state = replace(QualificationState(scope), display_state="DATA_INVALID", judgment_state="INVALID",
                                    reasons=(error_code,))
            result.append({
                "id": str(notice.id), "bid_notice_no": notice.bid_notice_no, "title": notice.title,
                "business_type": notice.business_type, "notice_kind": notice.notice_kind,
                "institution_name": notice.announcing_institution_name,
                "current_version": version.version_number, "notice_version_id": str(version.id),
                "case_id": str(case.id) if case else None, "state": state.to_dict() if state else None,
                "status_bucket": state_bucket(state, invalid=error_code is not None),
                "review_basis": "STORED_JUDGMENT" if state and state.selected_judgment_run_id else "NO_CURRENT_JUDGMENT",
            })
        # 조회 중 분석이 바뀌면 이전 상태를 그대로 반환하지 않고 재조회를 요청한다.
        if cases:
            ranked = _latest(QualificationAnalysisRun, QualificationAnalysisRun.notice_version_id,
                (QualificationAnalysisRun.notice_version_id.in_(list(cases)),))
            observed = db.execute(select(QualificationAnalysisRun.notice_version_id,
                QualificationAnalysisRun.id, QualificationAnalysisRun.status)
                .join(ranked, ranked.c.id == QualificationAnalysisRun.id).where(ranked.c.rank == 1)).all()
            if {(vid, aid, state) for vid, aid, state in observed} != original_basis:
                raise StateInputError("STATE_BASIS_CHANGED_DURING_READ")
        if rows:
            current_versions = db.execute(select(BidNoticeVersion.notice_id, BidNoticeVersion.id)
                .where(BidNoticeVersion.notice_id.in_([notice.id for notice, _ in rows]),
                       BidNoticeVersion.is_current.is_(True))).all()
            if set(current_versions) != {(notice.id, version.id) for notice, version in rows}:
                raise StateInputError("STATE_BASIS_CHANGED_DURING_READ")
        counts = {bucket: sum(item["status_bucket"] == bucket for item in result) for bucket in BUCKETS}
        filtered = [item for item in result if status is None or item["status_bucket"] == status]
        scope_hash = payload_fingerprint({"q": query, "business_type": business_type,
            "company_id": str(company_id) if company_id else None, "profile": profile_hash,
            "rows": [(item["id"], item["notice_version_id"], item["case_id"],
                      item["state"]["state_sha256"] if item["state"] else None) for item in result]})
        return {"contract_version": CATALOG_VERSION, "company_id": str(company_id) if company_id else None,
            "query": query, "business_type": business_type, "status_filter": status,
            "query_total": query_total, "scope_total": len(result), "total": len(filtered),
            "business_counts": business_counts, "status_counts": counts,
            "limit": limit, "offset": offset, "items": filtered[offset:offset+limit],
            "scope_sha256": scope_hash, "full_notice_eligibility_asserted": False}
