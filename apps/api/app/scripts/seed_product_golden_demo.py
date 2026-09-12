from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..auth_models import AppUser
from ..config import get_settings
from ..database import SessionLocal
from ..judgment_models import CompanyQualificationProfileCompleteness
from ..models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    CompanyCertification,
    CompanyIndustry,
    CompanyPerformance,
    CompanyPerformanceField,
    CompanyStaff,
    CompanyStaffRole,
    IndustryCode,
    PreflightCase,
    ProposalDocument,
)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_NOTICE_NO = "R26BK01715087"
DEMO_COMPANY_NAME = "그린브릿지 글로벌 주식회사"
DEMO_BUSINESS_NO = "9909080908"
DEMO_CASE_TITLE = "Golden Demo · 청년그린창업 해외진출 제안 검토"
DEMO_USERNAME = "golden-demo"
DEMO_PASSWORD = "golden-demo"

PROPOSAL_TEXT = """2026년 청년그린창업 스프링캠프 해외진출 기획 및 운영 용역 제안서 초안

1. 회사 개요
그린브릿지 글로벌 주식회사는 공공·창업 지원 프로그램과 해외진출 프로그램을 기획·운영하는 중소기업입니다.

2. 수행 전략
- 참여기업 진단 및 국가별 시장 적합성 분석
- 현지 바이어·투자자 매칭
- 해외 현지 프로그램 운영 및 결과 보고

3. 수행 조직
총괄 PM 1명, 프로그램 운영 4명, 해외 파트너십 3명, 콘텐츠·디자인 2명이 참여합니다.

4. 유사 수행 실적
최근 3년간 공공기관 및 창업지원기관의 글로벌 액셀러레이팅·해외진출 프로그램을 수행했습니다.

5. 제출 예정 자료
정성제안서, 정량제안서, 사업자등록 관련 서류, 국세·지방세 완납증명서, 참여인력 재직증명서와 자격 증빙을 제출합니다.

6. 확인 필요
발표자료 최종본과 정량평가 자기평가표 일부 증빙은 현재 취합 중입니다.
"""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def choose_demo_industry(db: Session) -> IndustryCode | None:
    for keyword in ("행사", "전시", "광고", "컨설팅", "정보통신"):
        row = db.scalar(
            select(IndustryCode)
            .where(IndustryCode.active.is_(True), IndustryCode.name.ilike(f"%{keyword}%"))
            .order_by(IndustryCode.code)
            .limit(1)
        )
        if row is not None:
            return row
    return db.scalar(
        select(IndustryCode).where(IndustryCode.active.is_(True)).order_by(IndustryCode.code).limit(1)
    )


def _get_notice_versions(db: Session, bid_notice_no: str) -> tuple[BidNotice, list[BidNoticeVersion]]:
    notice = db.scalar(select(BidNotice).where(BidNotice.bid_notice_no == bid_notice_no))
    if notice is None:
        raise ValueError(
            f"notice not found: {bid_notice_no}. Run bootstrap_product_data first."
        )
    versions = list(
        db.scalars(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.notice_id == notice.id)
            .order_by(BidNoticeVersion.version_number)
        ).all()
    )
    if not versions:
        raise ValueError(f"notice has no versions: {bid_notice_no}")
    return notice, versions


def seed_product_golden_demo(db: Session, *, bid_notice_no: str = DEFAULT_NOTICE_NO) -> dict[str, object]:
    if get_settings().app_environment == "production":
        raise RuntimeError("Product Golden demo seed cannot run in production")

    notice, versions = _get_notice_versions(db, bid_notice_no)
    baseline = versions[0]
    current = versions[-1]

    company = db.scalar(
        select(Company).where(Company.business_registration_number == DEMO_BUSINESS_NO)
    )
    created_company = company is None
    if company is None:
        company = Company(
            name=DEMO_COMPANY_NAME,
            business_registration_number=DEMO_BUSINESS_NO,
            region_code="11",
            region_name="서울특별시",
            company_size="SMALL",
        )
        db.add(company)
        db.flush()

        industry = choose_demo_industry(db)
        if industry is not None:
            db.add(CompanyIndustry(company_id=company.id, industry_code=industry.code, verified=True))

        db.add(CompanyStaff(company_id=company.id, total_count=18, verified=True))
        db.add_all(
            [
                CompanyStaffRole(company_id=company.id, role_name="PM", headcount=2, verified=True),
                CompanyStaffRole(company_id=company.id, role_name="프로그램 운영", headcount=6, verified=True),
                CompanyStaffRole(company_id=company.id, role_name="해외 파트너십", headcount=4, verified=True),
            ]
        )

        performance = CompanyPerformance(
            company_id=company.id,
            name="공공기관 글로벌 액셀러레이팅 프로그램 운영",
            client_name="합성 공공기관",
            client_institution_code=None,
            amount=Decimal("520000000"),
            started_at=date(2025, 3, 1),
            completed_at=date(2025, 11, 30),
            description="청년창업기업 해외진출·바이어 매칭·현지 프로그램 운영",
            verified=True,
        )
        db.add(performance)
        db.flush()
        db.add_all(
            [
                CompanyPerformanceField(performance_id=performance.id, field_name="해외진출"),
                CompanyPerformanceField(performance_id=performance.id, field_name="창업지원"),
                CompanyPerformanceField(performance_id=performance.id, field_name="행사운영"),
            ]
        )

        db.add_all(
            [
                CompanyCertification(
                    company_id=company.id,
                    name="중소기업확인서",
                    certificate_number="DEMO-SME-2026-001",
                    issuer_name="중소벤처기업부",
                    issued_at=date(2026, 1, 1),
                    expires_at=date(2026, 12, 31),
                    verified=True,
                ),
                CompanyCertification(
                    company_id=company.id,
                    name="직접생산확인증명서",
                    certificate_number="DEMO-DIRECT-2026-001",
                    issuer_name="중소기업유통센터",
                    issued_at=date(2026, 1, 1),
                    expires_at=date(2027, 12, 31),
                    verified=True,
                ),
            ]
        )
        db.add(
            CompanyQualificationProfileCompleteness(
                company_id=company.id,
                region_complete=True,
                company_size_complete=True,
                industries_complete=True,
                staff_total_complete=True,
                staff_roles_complete=True,
                performances_complete=True,
                certifications_complete=True,
            )
        )
        db.flush()

    user = db.scalar(select(AppUser).where(AppUser.username == DEMO_USERNAME))
    created_user = user is None
    if user is None:
        user = AppUser(
            username=DEMO_USERNAME,
            password_hash=hash_password(DEMO_PASSWORD),
            company_id=company.id,
            role="ADMIN",
            active=True,
        )
        db.add(user)
    else:
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.company_id = company.id
        user.role = "ADMIN"
        user.active = True

    case = db.scalar(
        select(PreflightCase).where(
            PreflightCase.company_id == company.id,
            PreflightCase.notice_id == notice.id,
            PreflightCase.title == DEMO_CASE_TITLE,
        )
    )
    created_case = case is None
    if case is None:
        case = PreflightCase(
            company_id=company.id,
            notice_id=notice.id,
            baseline_version_id=baseline.id,
            current_version_id=current.id,
            title=DEMO_CASE_TITLE,
            status="READY",
        )
        db.add(case)
        db.flush()

    proposal = db.scalar(
        select(ProposalDocument).where(
            ProposalDocument.case_id == case.id,
            ProposalDocument.name == "Golden Demo 제안서 초안.txt",
        )
    )
    created_proposal = proposal is None
    if proposal is None:
        settings = get_settings()
        storage_key = f"product-golden/{case.id}/proposal-draft.txt"
        if settings.document_storage_backend.strip().upper() == "LOCAL":
            target = Path(settings.document_storage_path) / storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(PROPOSAL_TEXT, encoding="utf-8")

        now = datetime.now(KST)
        text_sha = _sha256_text(PROPOSAL_TEXT)
        proposal = ProposalDocument(
            case_id=case.id,
            document_order=0,
            role="PROPOSAL",
            name="Golden Demo 제안서 초안.txt",
            storage_status="STORED",
            storage_key=storage_key,
            content_type="text/plain; charset=utf-8",
            file_size_bytes=len(PROPOSAL_TEXT.encode("utf-8")),
            file_sha256=text_sha,
            stored_at=now,
            storage_error=None,
            extraction_status="EXTRACTED",
            extracted_text=PROPOSAL_TEXT,
            extracted_blocks=[{"block_index": 0, "kind": "text", "text": PROPOSAL_TEXT}],
            extracted_char_count=len(PROPOSAL_TEXT),
            extracted_text_sha256=text_sha,
            text_extractor="PLAIN_TEXT",
            extracted_at=now,
            extraction_error=None,
        )
        db.add(proposal)

    db.commit()
    return {
        "notice": {"bid_notice_no": notice.bid_notice_no, "title": notice.title, "versions": len(versions)},
        "company": {"id": str(company.id), "name": company.name, "created": created_company},
        "login": {
            "username": DEMO_USERNAME,
            "password": DEMO_PASSWORD,
            "created": created_user,
        },
        "case": {
            "id": str(case.id),
            "title": case.title,
            "baseline_version": baseline.version_number,
            "current_version": current.version_number,
            "created": created_case,
        },
        "proposal": {"name": proposal.name, "created": created_proposal},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Product Golden demo into the local DB.")
    parser.add_argument("--notice-no", default=DEFAULT_NOTICE_NO)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = seed_product_golden_demo(db, bid_notice_no=args.notice_no)
        print("Product Golden demo ready")
        print(f"notice: {result['notice']['bid_notice_no']} / versions={result['notice']['versions']}")
        print(f"company: {result['company']['name']}")
        print(f"login: {result['login']['username']} / {result['login']['password']}")
        print(f"case: {result['case']['title']}")
        print(f"versions: v{result['case']['baseline_version']} -> v{result['case']['current_version']}")
        print(f"proposal: {result['proposal']['name']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
