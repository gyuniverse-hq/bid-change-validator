"""Rendering a finished review as plain text.

Two things consume this: the CLI prints it, and `narrate_report` reads it back as
prose. Keeping one renderer means the briefing an officer hears is generated from
exactly the text they can also read — if the two drifted apart, the spoken version
could describe verdicts the printed one does not contain.

Every line here is already-settled output. Nothing in this module decides anything.
"""

from __future__ import annotations

from .pipeline import EligibilityReport


STATUS_LABELS = {"SATISFIED": "충족", "UNSATISFIED": "미충족", "UNKNOWN": "확인 불가"}


def render_report_text(report: EligibilityReport) -> str:
    """Render the whole review as a plain-text report."""
    notice = report.notice
    lines: list[str] = [
        f"[공고] {report.notice_no}-{notice.notice_order or '000'} {notice.title or ''}",
    ]
    for label, value in (
        ("공고기관", notice.institution),
        ("업무구분", notice.business_type_name),
        ("계약방법", notice.contract_method),
        ("입찰마감", notice.bid_close_at),
    ):
        if value:
            lines.append(f"  {label}: {value}")
    price_lines = notice.price.as_display_lines()
    if price_lines:
        lines.append("  계약가격: " + " / ".join(price_lines))

    if report.company_name or report.profile_id:
        lines.append("")
        lines.append(f"[검토 대상] {report.company_name or ''} ({report.profile_id or ''})")
        if report.is_demo_profile:
            lines.append("  ※ 시연용 가상 회사이며 실제 존재하는 업체가 아닙니다.")

    tally = report.counts()
    lines.append("")
    lines.append(f"[참가자격 판정] {report.verdict_label}")
    lines.append(
        f"  충족 {tally['SATISFIED']} / 미충족 {tally['UNSATISFIED']} / "
        f"확인 불가 {tally['UNKNOWN']}"
    )

    requirement_by_key = {item.requirement_key: item for item in report.requirements}
    for judgment in report.judgments:
        requirement = requirement_by_key.get(judgment.requirement_key)
        source = (requirement.raw if requirement else judgment.requirement_key) or ""
        lines.append(f"  - [{STATUS_LABELS[judgment.status]}] {source[:70]}")
        lines.append(f"      근거: {judgment.reason}")
        if judgment.follow_up_question:
            lines.append(f"      되묻기: {judgment.follow_up_question}")

    flagged = report.flagged_clauses()
    if flagged:
        lines.append("")
        lines.append(f"[확인 필요 계약조항] {len(flagged)}건")
        for finding in flagged:
            label = f"{finding.clause_label}항 " if finding.clause_label else ""
            lines.append(f"  - {label}{finding.risk_type}: {finding.reason}")
            if finding.standard and finding.standard.clause_ref:
                lines.append(
                    f"      표준: {finding.standard.description}"
                    f" ({finding.standard.clause_ref})"
                )

    if report.diagnostics:
        lines.append("")
        lines.append("[공고 제한·참고 사항]")
        for item in report.diagnostics:
            message = item.get("message")
            if message:
                lines.append(f"  - {message}")

    if report.industries:
        lines.append("")
        lines.append("[업종 및 근거법규]")
        for note in report.industries:
            origin = "공고" if note.source == "NOTICE" else "업체"
            parts = [f"  - [{origin}] {note.code} {note.name or '(코드 미상)'}"]
            if note.legal_basis:
                parts.append(f"근거 {note.legal_basis}")
            lines.append(" · ".join(parts))

    return "\n".join(lines)
