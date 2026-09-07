"""Run the eligibility demo: one notice, one fictional company, one verdict.

    python scripts/run_eligibility_demo.py --list
    python scripts/run_eligibility_demo.py R26BK01705963 --profile DEMO_적격업체
    python scripts/run_eligibility_demo.py R26BK01705963 --profile DEMO_적격업체 --live
    python scripts/run_eligibility_demo.py R26BK01705963 --rfp path/to/notice.txt --summary

Fixtures are used by default so the demo runs with no key and no network. `--live`
calls 입찰공고정보서비스 for real and caches what it gets, so the same run can be
replayed offline afterwards.

The verdict comes from code alone. `--summary` additionally asks the model to
describe the notice in prose; that text is never read back by any rule.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from apps.api.app.ai.contracts import Judgment  # noqa: E402
from apps.api.app.demo import (  # noqa: E402
    ChainedNoticeSource,
    CsvIndustryCatalog,
    EligibilityReport,
    FileProfileStore,
    FixtureNoticeSource,
    G2BNoticeSource,
    NoticePriceBoard,
    review_notice,
)

STATUS_MARK = {"SATISFIED": "충족", "UNSATISFIED": "미충족", "UNKNOWN": "확인 불가"}
RULE = "─" * 72


def _unquote(value: str) -> str:
    """Strip one layer of surrounding quotes, the way dotenv readers do.

    `.env` files are commonly written as KEY='value'. Sending those quotes on to
    an API produces an authentication failure that reads exactly like a revoked
    key, so this is worth getting right rather than debugging twice.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_env() -> dict[str, str]:
    """Read .env without adding a dependency; real env vars win."""
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = _unquote(value)
    values.update(
        {
            key: _unquote(value)
            for key, value in os.environ.items()
            if key in values or key.startswith(("G2B_", "OPENAI_"))
        }
    )
    return values


def _print_notice(report: EligibilityReport) -> None:
    notice = report.notice
    print(RULE)
    print(f"공고 {report.notice_no}-{notice.notice_order or '000'}  {notice.title or ''}")
    print(RULE)
    for label, value in (
        ("공고기관", notice.institution),
        ("수요기관", notice.demand_institution),
        ("업무구분", notice.business_type_name),
        ("계약방법", notice.contract_method),
        ("분류", notice.classification),
        ("입찰마감", notice.bid_close_at),
        ("개찰", notice.opening_at),
    ):
        if value:
            print(f"  {label:8s} {value}")

    price_lines = notice.price.as_display_lines()
    if price_lines:
        print(f"  {'계약가격':8s} " + " / ".join(price_lines))
    if notice.detail_url:
        print(f"  {'공고상세':8s} {notice.detail_url}")


def _print_summary(report: EligibilityReport) -> None:
    print()
    print("■ 공고 내용 요약 (LLM 서술 — 판정 아님)")
    if report.summary.available:
        print(f"  {report.summary.text}")
    else:
        print(f"  (요약 없음 — {report.summary.notes})")


def _print_company(report: EligibilityReport) -> None:
    print()
    print("■ 검토 대상 업체")
    print(f"  {report.company_name or '(이름 없음)'}  [{report.profile_id}]")
    if report.is_demo_profile:
        print("  ※ 시연용 가상 회사입니다. 실제 존재하는 업체가 아닙니다.")
    if report.scenario:
        print(f"  시나리오: {report.scenario}")


def _print_judgments(report: EligibilityReport) -> None:
    print()
    print(f"■ 참가자격 판정: {report.verdict_label}")
    tally = report.counts()
    print(
        f"  충족 {tally['SATISFIED']} / 미충족 {tally['UNSATISFIED']} / "
        f"확인 불가 {tally['UNKNOWN']}"
    )
    if not report.judgments:
        print("  (공고 API 필드에서 판정 가능한 자격요건을 찾지 못했습니다)")
        return

    by_key = {item.requirement_key: item for item in report.requirements}
    for judgment in report.judgments:
        requirement = by_key.get(judgment.requirement_key)
        print()
        print(f"  [{STATUS_MARK[judgment.status]}] {requirement.raw if requirement else ''}")
        print(f"       근거: {judgment.reason}")
        if judgment.requires_evidence:
            print("       ※ 증빙 서류 확인 필요 (업체 자기신고)")
        if judgment.follow_up_question:
            print(f"       되묻기: {judgment.follow_up_question}")


def _print_clauses(report: EligibilityReport) -> None:
    if not report.clause_findings:
        return
    flagged = report.flagged_clauses()
    print()
    print(f"■ 확인 필요 계약조항: {len(flagged)}건 (검토 {len(report.clause_findings)}건)")
    for finding in flagged:
        label = f"[{finding.clause_label}] " if finding.clause_label else ""
        print(f"  · {label}{finding.risk_type} — {finding.reason}")
        if finding.matched_text:
            print(f"      원문: {finding.matched_text}")
        if finding.standard and finding.standard.clause_ref:
            print(
                f"      표준: {finding.standard.description}"
                f" ({finding.standard.clause_ref})"
            )
    undetermined = [f for f in report.clause_findings if f.verdict == "UNDETERMINED"]
    for finding in undetermined:
        print(f"  ? {finding.risk_type} — {finding.reason}")


def _print_diagnostics(report: EligibilityReport) -> None:
    if not report.diagnostics:
        return
    print()
    print("■ 공고에서 확인된 제한·참고 사항")
    for item in report.diagnostics:
        mark = "!" if item.get("severity") == "WARNING" else "-"
        print(f"  {mark} {item.get('message')}")


def _print_industries(report: EligibilityReport) -> None:
    if not report.industries:
        return
    print()
    print("■ 업종 및 근거법규")
    for note in report.industries:
        origin = "공고" if note.source == "NOTICE" else "업체"
        name = note.name or "(코드 미상)"
        line = f"  [{origin}] {note.code} {name}"
        if note.classification:
            line += f" · {note.classification}"
        if note.legal_basis:
            line += f" · 근거 {note.legal_basis}"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notice_no", nargs="?", help="입찰공고번호 (예: R26BK01705963)")
    parser.add_argument("--profile", help="가상 회사 프로필 id")
    parser.add_argument("--list", action="store_true", help="사용 가능한 공고·프로필 출력")
    parser.add_argument("--live", action="store_true", help="나라장터 API를 실제로 호출")
    parser.add_argument("--rfp", type=Path, help="공고문 텍스트 파일 (요건 추출·조항 검토·요약에 사용)")
    parser.add_argument("--summary", action="store_true", help="LLM 요약 생성")
    parser.add_argument(
        "--extract",
        action="store_true",
        help="공고문에서 자격요건을 LLM으로 추출해 판정에 포함 (OPENAI_API_KEY 필요)",
    )
    parser.add_argument(
        "--deep-clause",
        action="store_true",
        help="정규식이 못 찾은 조항을 임베딩+LLM으로 보강 탐지 (OPENAI_API_KEY 필요)",
    )
    parser.add_argument("--narrative", action="store_true", help="판정 결과를 문장으로 브리핑")
    parser.add_argument("--assist", metavar="질문", help="현재 판정 상태에 대해 도우미에게 질문")
    args = parser.parse_args()

    env = _load_env()
    fixtures = FixtureNoticeSource()
    profiles = FileProfileStore()

    if args.list or not args.notice_no:
        print("사용 가능한 공고 (fixture):")
        for notice_no in fixtures.available() or ["(없음 — --live 로 조회하세요)"]:
            print(f"  {notice_no}")
        print("\n사용 가능한 가상 회사 프로필:")
        for profile_id in profiles.list_ids():
            print(f"  {profile_id}  — {profiles.scenario(profile_id) or ''}")
        return 0 if args.list else 2

    notice_source = fixtures
    if args.live:
        service_key = env.get("G2B_SERVICE_KEY")
        if not service_key:
            print("G2B_SERVICE_KEY 가 설정되지 않아 --live 를 쓸 수 없습니다.", file=sys.stderr)
            return 2
        live = G2BNoticeSource(
            service_key=service_key,
            base_url=env.get("G2B_BASE_URL")
            or "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
            cache_dir=fixtures.directory,
        )
        # Live first so a re-run picks up corrections, fixtures as the fallback.
        notice_source = ChainedNoticeSource(live, fixtures)

    narrate = None
    if args.summary or args.narrative or args.assist:
        from apps.api.app.ai.providers import OpenAINarrator

        narrator = OpenAINarrator(api_key=env.get("OPENAI_API_KEY"))
        narrate = narrator if narrator.available else None
        if narrate is None:
            print("(OPENAI_API_KEY 미설정 — 요약을 생성하지 않습니다)", file=sys.stderr)

    rfp_text = args.rfp.read_text(encoding="utf-8") if args.rfp else None

    structured_extract = None
    if args.extract:
        from apps.api.app.ai.providers import OpenAIStructuredExtractor

        extractor = OpenAIStructuredExtractor(api_key=env.get("OPENAI_API_KEY"))
        structured_extract = extractor if extractor.available else None
        if structured_extract is None:
            print("(OPENAI_API_KEY 미설정 — 공고문 요건 추출을 건너뜁니다)", file=sys.stderr)

    # Clause review needs the published rules; without the index it is skipped
    # rather than compared against nothing.
    standard_clauses = None
    index_path = REPO_ROOT / "data" / "standards" / "clauses.json"
    if rfp_text and index_path.exists():
        from apps.api.app.ai.clause_review.standards import load_clauses

        standard_clauses = load_clauses(index_path)

    report = review_notice(
        args.notice_no,
        notice_source=notice_source,
        profile_id=args.profile,
        profile_store=profiles,
        industry_catalog=CsvIndustryCatalog(),
        price_board=NoticePriceBoard(),
        narrate=narrate,
        rfp_text=rfp_text,
        standard_clauses=standard_clauses,
        structured_extract=structured_extract,
        use_embedding_fallback=args.deep_clause,
    )
    if report is None:
        print(f"공고 {args.notice_no} 를 찾지 못했습니다. --live 를 붙여보세요.", file=sys.stderr)
        return 1

    _print_notice(report)
    if args.summary or args.rfp:
        _print_summary(report)
    if args.profile:
        _print_company(report)
        _print_judgments(report)
    _print_clauses(report)
    _print_diagnostics(report)
    _print_industries(report)

    if args.narrative:
        from apps.api.app.ai.summary import narrate_report
        from apps.api.app.demo import render_report_text

        told = narrate_report(render_report_text(report), narrate=narrate)
        print()
        print("■ 브리핑 (LLM 서술 — 판정은 위 코드 결과가 기준)")
        print(f"  {told.text}" if told.available else f"  (생략 — {told.notes})")

    if args.assist:
        from apps.api.app.ai.assist import answer_question, summarize_state

        state = summarize_state(
            profile=profiles.get(args.profile) if args.profile else None,
            judgments=report.judgments,
            requirements=report.requirements,
            clause_findings=report.clause_findings,
            notice_title=report.notice.title,
            diagnostics=report.diagnostics,
        )
        answer = answer_question(args.assist, state_summary=state, narrate=narrate)
        print()
        print(f"■ 도우미  Q. {args.assist}")
        print(f"  {answer.text}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
