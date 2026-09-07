"""Deterministic judgment of canonical qualification requirements.

This closes the loop the AI package was built around:

    extracted requirements + company profile -> Judgment

The model is not in this file and must not be. Extraction turns prose into
structured fields, normalization turns source strings into numbers, and this
module compares the two in plain code. A model that both reads the notice and
decides whether the company qualifies has no independent step left to catch it
being wrong.

Three rules shape everything here:

1. **Missing data never becomes a decision.** A requirement the profile cannot
   answer produces UNKNOWN plus a follow-up question, never UNSATISFIED.
2. **Uncertainty is reported, not resolved.** Profile performances carry a year
   and no month, so a "최근 3년" boundary year is genuinely undecidable; those rows
   are set aside and the requirement goes to review instead of being guessed.
3. **The core stays industry-neutral.** Requirements needing industry-specific
   vocabulary are handed to `app.ai.extensions`, which asks for that field only
   when a notice requires it.

Follow-up question wording may come from a model, so `question_writer` is
injectable exactly like the structured extractor in `analysis_pipeline`. The
default is a template, which keeps the whole module network-free and testable.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import extensions
from .analysis_result import RequirementAnalysisResult
from .contracts import (
    BasisType,
    Judgment,
    JudgmentStatus,
    QualificationRequirement,
    ReasonCode,
)
from .normalization import normalize_count
from .profile import (
    EVIDENCE_DECLARED,
    EVIDENCE_VERIFIED,
    SIZE_LABELS,
    SIZE_SMALL,
    Certification,
    Performance,
    ProfileView,
    StaffMember,
    as_profile_view,
)


RULE_VERSION = "judgment.v1"

QuestionWriter = Callable[[QualificationRequirement], str]

# "경력 5년 이상" — a requirement stated in years of experience.
_STAFF_CAREER_RE = re.compile(r"경력[^.\n]{0,10}?(\d+)\s*년\s*이상")
# "기술인력 3인 이상" — a headcount with no grade attached.
_STAFF_COUNT_RE = re.compile(r"(?:기술)?인력[^.\n]{0,12}?(\d+\s*[인명])\s*이상")

_TOKEN_SPLIT_RE = re.compile(r"[0-9]+|[A-Za-z]+|[가-힣]+")

# Period wording, used to tell "the notice stated no time window" apart from
# "a time window was stated and we failed to normalize it".
_PERIOD_MENTION_RE = re.compile(r"최근|이내|이후|년\s*간|개월|연간|년도|년\s*이내")

# Company-size restrictions appear in notices of every industry.
# "대기업 및 중견기업 참여 제한", "대기업 사업자는 입찰에 참여 불가"
_SIZE_EXCLUDE_RE = re.compile(
    r"(대기업|중견기업|중견\s*기업)[^.\n]{0,40}?"
    r"(?:참여\s*(?:제한|불가|배제)|입찰\s*참가\s*제한|참가\s*불가|제외)"
)
# "중소기업만 참여 가능", "중소기업자간 경쟁제품"
_SIZE_REQUIRE_SME_RE = re.compile(r"중소기업(?:자)?[^.\n]{0,20}?(?:만|한정|대상으?로|간\s*경쟁)")
# Group affiliation is a different fact from size and is not in the core profile.
_AFFILIATE_RE = re.compile(r"상호출자제한|기업집단|계열\s*(?:회사|사)")

_NO_REGION_LIMIT = ("전국", "제한없음", "제한 없음")

_CERT_KIND_LABELS = {
    "LICENSE": "면허",
    "CERTIFICATION": "인증",
    "REGISTRATION": "등록",
}

_OP_LABELS = {">=": "≥", ">": ">", "<=": "≤", "<": "<", "=": "="}


def _compare(have: float, operator: str | None, need: float) -> bool:
    if operator == ">":
        return have > need
    if operator == "<=":
        return have <= need
    if operator == "<":
        return have < need
    if operator == "=":
        return have == need
    return have >= need


def _op_label(operator: str | None) -> str:
    return _OP_LABELS.get(operator or ">=", "≥")


def _name_matches(held: str, requirement_text: str) -> bool:
    """Does a held name refer to what the requirement asks for?

    Tokenizing on letter/digit boundaries as well as separators is what makes
    "ISO27001" match "ISO/IEC 27001": split on separators alone leaves one
    "ISO27001" token that appears nowhere in the requirement text.
    """
    tokens = [token for token in _TOKEN_SPLIT_RE.findall(held or "") if len(token) >= 2]
    if not tokens:
        return False
    target = (requirement_text or "").lower()
    return all(token.lower() in target for token in tokens)


def _evidence_note(statuses: list[str]) -> str:
    """Surface self-declared items. A satisfied judgment resting on unchecked
    paperwork has to say so, or the user reads it as confirmed."""
    declared = EVIDENCE_DECLARED in statuses
    verified = EVIDENCE_VERIFIED in statuses
    if declared and not verified:
        return " (업체 자기신고 — 증빙 미확인)"
    if declared and verified:
        return " (일부는 업체 자기신고 — 증빙 미확인)"
    return ""


def _amounts(performances: list[Performance]) -> tuple[float, float]:
    total = sum(item.amount or 0 for item in performances)
    best = max((item.amount or 0 for item in performances), default=0)
    return total, best


def _split_by_period(
    view: ProfileView, months: float | None, *, today: date
) -> tuple[list[Performance], list[Performance]]:
    """Split performances into (certainly inside the window, undecidable).

    The profile records a completion year and no month, so the year the window
    boundary falls in cannot be resolved. If today is 2026-09 and the window is
    "최근 3년", a 2023 project completed in January is outside and one completed in
    December is inside. Those rows go to the uncertain bucket rather than being
    counted either way.
    """
    if months is None:
        return view.performances, []

    years = months / 12.0
    boundary_year = (
        today.year - int(years) if months % 12 == 0 or years >= 1 else today.year
    )
    inside: list[Performance] = []
    uncertain: list[Performance] = []
    for performance in view.performances:
        year = performance.year
        if year is None:
            uncertain.append(performance)  # no year at all, cannot place it
        elif year > boundary_year:
            inside.append(performance)
        elif year == boundary_year:
            uncertain.append(performance)
        # year < boundary_year is certainly outside the window and is dropped
    return inside, uncertain


@dataclass
class _Context:
    view: ProfileView
    today: date
    question_writer: QuestionWriter | None = None

    def question(self, requirement: QualificationRequirement) -> str:
        raw = (requirement.raw or "").strip()
        template = (
            f"'{raw[:60]}' 요건과 관련된 정보가 프로필에 없습니다. 해당 요건을 충족하시나요?"
        )
        if self.question_writer is None:
            return template
        try:
            written = (self.question_writer(requirement) or "").strip()
        except Exception:
            return template
        return written.splitlines()[0][:200] if written else template


@dataclass
class _Draft:
    """A judgment under construction, before it becomes the shared contract."""

    status: JudgmentStatus = "UNKNOWN"
    reason_code: ReasonCode = "NEEDS_REVIEW"
    reason: str = ""
    question: str | None = None
    extension_key: str | None = None
    basis_type: BasisType = "NONE"
    profile_refs: list[dict[str, str]] = field(default_factory=list)
    evidence_statuses: list[str] = field(default_factory=list)

    def satisfied(self, reason: str) -> None:
        self.status = "SATISFIED"
        self.reason_code = "RULE_MATCH"
        self.reason = reason

    def unsatisfied(self, reason: str) -> None:
        self.status = "UNSATISFIED"
        self.reason_code = "RULE_MISMATCH"
        self.reason = reason

    def insufficient(self, reason: str, question: str | None = None) -> None:
        self.status = "UNKNOWN"
        self.reason_code = "INSUFFICIENT_DATA"
        self.reason = reason
        self.question = question

    def review(self, reason: str, question: str | None = None) -> None:
        self.status = "UNKNOWN"
        self.reason_code = "NEEDS_REVIEW"
        self.reason = reason
        self.question = question

    def unsupported(self, reason: str, question: str | None = None) -> None:
        self.status = "UNKNOWN"
        self.reason_code = "UNSUPPORTED_REQUIREMENT"
        self.reason = reason
        self.question = question

    def cite(
        self,
        section: str,
        items: list[Performance] | list[Certification] | list[StaffMember],
    ) -> None:
        """Record which profile rows backed this judgment."""
        self.basis_type = "PROFILE"
        for index, item in enumerate(items):
            self.evidence_statuses.append(item.evidence_status)
            identifier = (
                getattr(item, "id", None)
                or getattr(item, "label", None)
                or getattr(item, "code", None)
                or index
            )
            self.profile_refs.append({"section": section, "id": str(identifier)})

    def cite_values(self, section: str, values: list[str]) -> None:
        self.basis_type = "PROFILE"
        for value in values:
            self.profile_refs.append({"section": section, "value": str(value)})

    @property
    def note(self) -> str:
        return _evidence_note(self.evidence_statuses)


# ── requirement rules ────────────────────────────────────────────────────
def _judge_performance_amount(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    if not view.has("performances"):
        draft.insufficient("프로필에 실적 정보 없음", ctx.question(requirement))
        return
    if requirement.operator == "RANGE":
        draft.review(
            "실적 금액이 범위 조건으로 제시되어 자동 판정 기준을 확정하지 못함 — 담당자 확인 필요",
            ctx.question(requirement),
        )
        return
    need = requirement.value
    if not isinstance(need, (int, float)):
        draft.review("실적 요구 금액을 수치로 확정하지 못함 — 확인 불가", ctx.question(requirement))
        return

    months = requirement.period_months
    if months is None and _PERIOD_MENTION_RE.search(requirement.raw or ""):
        draft.review(
            "요건에 실적 인정 기간이 있으나 수치로 확정하지 못함 — 확인 불가",
            ctx.question(requirement),
        )
        return

    inside, uncertain = _split_by_period(view, months, today=ctx.today)
    draft.cite("performances", inside + uncertain)
    in_total, in_best = _amounts(inside)
    all_total, all_best = _amounts(inside + uncertain)
    note = draft.note
    window = f"최근 {months:.0f}개월 " if months is not None else ""
    symbol = _op_label(requirement.operator)
    aggregation = str(requirement.scope.get("aggregation") or "UNSPECIFIED").upper()

    def meets(value: float) -> bool:
        return _compare(value, requirement.operator, float(need))

    boundary_question = "해당 실적을 정확히 몇 년 몇 월에 완료하셨는지 알려주시겠어요?"
    boundary_reason = (
        "완료 연도가 기간 경계에 걸치는 실적을 포함해야 충족됩니다 "
        "(프로필은 완료 연도만 보유) — 완료 시점 확인 필요"
    )

    if aggregation == "TOTAL":
        if meets(in_total):
            draft.satisfied(
                f"{window}실적 합산 {in_total:,.0f}원 {symbol} {need:,.0f}원{note}"
            )
        elif meets(all_total):
            draft.review(boundary_reason, boundary_question)
        else:
            draft.unsatisfied(
                f"{window}실적 합산 {all_total:,.0f}원, 요구 {symbol} {need:,.0f}원 미달{note}"
            )
        return

    if aggregation == "SINGLE":
        if meets(in_best):
            draft.satisfied(
                f"{window}최대 단건 실적 {in_best:,.0f}원 {symbol} {need:,.0f}원{note}"
            )
        elif meets(all_best):
            draft.review(boundary_reason, boundary_question)
        else:
            draft.unsatisfied(
                f"{window}최대 단건 실적 {all_best:,.0f}원, 요구 {symbol} {need:,.0f}원 미달{note}"
            )
        return

    # Aggregation unstated. The single-contract reading is the strict one, so it
    # is tried first; a result that only holds on the summed reading is reported
    # as needing confirmation rather than claimed.
    if meets(in_best):
        draft.satisfied(f"{window}최대 단건 실적 {in_best:,.0f}원 {symbol} {need:,.0f}원{note}")
        return
    if meets(all_best):
        draft.review(boundary_reason, boundary_question)
        return
    if meets(in_total):
        draft.review(
            f"단건 최대 {in_best:,.0f}원으로는 미달이나 합산 {in_total:,.0f}원은 충족 — "
            f"단건/합산 기준 확인 필요{note}",
            "해당 실적요건이 단일 계약 기준인지 합산 기준인지 확인해 주시겠어요?",
        )
        return
    if meets(all_total):
        draft.review(
            f"경계 연도 실적을 포함해야 합산 {all_total:,.0f}원으로 충족됩니다 — "
            f"완료 시점과 단건/합산 기준을 함께 확인해야 합니다",
            "해당 실적의 완료 시점과, 요건이 단건 기준인지 합산 기준인지 알려주시겠어요?",
        )
        return
    draft.unsatisfied(
        f"{window}실적 합산 {all_total:,.0f}원, 요구 {symbol} {need:,.0f}원 미달{note}"
    )


def _judge_performance_count(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    if not view.has("performances"):
        draft.insufficient("프로필에 실적 정보 없음", ctx.question(requirement))
        return
    need = requirement.value
    if not isinstance(need, (int, float)):
        draft.review("실적 요구 건수를 수치로 확정하지 못함 — 확인 불가", ctx.question(requirement))
        return

    months = requirement.period_months
    if months is None and _PERIOD_MENTION_RE.search(requirement.raw or ""):
        draft.review(
            "요건에 실적 인정 기간이 있으나 수치로 확정하지 못함 — 확인 불가",
            ctx.question(requirement),
        )
        return

    inside, uncertain = _split_by_period(view, months, today=ctx.today)
    draft.cite("performances", inside + uncertain)
    note = draft.note
    window = f"최근 {months:.0f}개월 " if months is not None else ""
    symbol = _op_label(requirement.operator)

    def meets(value: float) -> bool:
        return _compare(value, requirement.operator, float(need))

    if meets(len(inside)):
        draft.satisfied(f"{window}실적 {len(inside)}건 {symbol} {need:.0f}건{note}")
        return
    if meets(len(inside) + len(uncertain)):
        draft.review(
            f"기간 경계에 걸치는 실적 {len(uncertain)}건을 포함해야 {need:.0f}건이 됩니다 "
            f"(프로필은 완료 연도만 보유) — 완료 시점 확인 필요",
            "해당 실적을 정확히 몇 년 몇 월에 완료하셨는지 알려주시겠어요?",
        )
        return
    draft.unsatisfied(
        f"{window}실적 {len(inside) + len(uncertain)}건, 요구 {symbol} {need:.0f}건 미달{note}"
    )


def _judge_certification(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    kind = _CERT_KIND_LABELS.get(str(requirement.scope.get("kind") or ""), "자격")
    if not view.has("certifications"):
        draft.insufficient(f"프로필에 {kind} 정보 없음", ctx.question(requirement))
        return

    target = str(requirement.value or "").strip()
    names = view.certification_labels()
    hits = [
        name
        for name in names
        if (target and _name_matches(name, target)) or _name_matches(name, requirement.raw)
    ]
    if hits:
        matched = [
            item
            for item in view.certifications
            if (item.label or item.code or "").strip() in hits
        ]
        draft.cite("certifications", matched)
        draft.satisfied(f"보유 {kind} {hits} 일치{draft.note}")
        return
    if names:
        draft.review(
            f"보유 목록 {names} 중 요건과 일치하는 항목 없음 — 명칭 확인 필요",
            ctx.question(requirement),
        )
        return
    draft.basis_type = "PROFILE"
    draft.unsatisfied(f"보유 {kind} 없음(프로필에 빈 목록으로 명시)")


def _judge_region(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    target = f"{requirement.value or ''} {requirement.raw or ''}"
    if any(token in target for token in _NO_REGION_LIMIT):
        draft.satisfied("지역 제한 없음")
        return
    if not view.has("region"):
        draft.insufficient("프로필에 소재지역 정보 없음", ctx.question(requirement))
        return

    label = view.region_label or ""
    code = view.region_code or ""
    draft.cite_values("basic.region", [label or code])
    tokens = [token for token in re.split(r"\s+", label) if token]
    if any(token in target for token in tokens) or (label[:2] and label[:2] in target):
        draft.satisfied(f"소재지 '{label}'이 요건 명시 지역과 일치")
        return
    if code and code in target:
        draft.satisfied(f"소재지 행정구역 코드 '{code}'가 요건과 일치")
        return
    draft.review(
        f"소재지 '{label}'과 요건 문언 불일치 여부 확인 필요", ctx.question(requirement)
    )


def _judge_staff(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    if not view.has("staff"):
        draft.insufficient("프로필에 인력 정보 없음", ctx.question(requirement))
        return
    staff = view.staff
    raw = requirement.raw or ""

    # (1) years of experience — decidable from career_years
    career_match = _STAFF_CAREER_RE.search(raw)
    if career_match:
        need_years = int(career_match.group(1))
        known = [item for item in staff if item.career_years is not None]
        if not known:
            draft.insufficient(
                "프로필 인력에 경력 연수 정보가 없어 판정 보류", ctx.question(requirement)
            )
            return
        qualified = [item for item in known if (item.career_years or 0) >= need_years]
        need_people = _required_headcount(requirement, raw)
        draft.cite("staff", qualified or known)
        if len(qualified) >= need_people:
            draft.satisfied(
                f"경력 {need_years}년 이상 인력 {len(qualified)}명 ≥ 요구 {need_people}명{draft.note}"
            )
        else:
            draft.unsatisfied(
                f"경력 {need_years}년 이상 인력 {len(qualified)}명 < 요구 {need_people}명"
            )
        return

    # (2) headcount only
    if requirement.unit == "PERSON" and isinstance(requirement.value, (int, float)):
        need_people = int(requirement.value)
        draft.cite("staff", staff)
        symbol = _op_label(requirement.operator)
        if _compare(len(staff), requirement.operator, need_people):
            draft.satisfied(f"보유 인력 {len(staff)}명 {symbol} {need_people}명{draft.note}")
        else:
            draft.unsatisfied(f"보유 인력 {len(staff)}명, 요구 {symbol} {need_people}명 미달")
        return

    count_match = _STAFF_COUNT_RE.search(raw)
    if count_match:
        normalized = normalize_count(count_match.group(1))
        if normalized["parse_status"] == "success":
            need_people = int(normalized["value"])
            draft.cite("staff", staff)
            if len(staff) >= need_people:
                draft.satisfied(f"보유 인력 {len(staff)}명 ≥ 요구 {need_people}명{draft.note}")
            else:
                draft.unsatisfied(f"보유 인력 {len(staff)}명 < 요구 {need_people}명")
            return

    # (3) a named role with no number attached
    role = str(requirement.scope.get("role") or requirement.value or "").strip()
    if role:
        matched = [item for item in staff if item.role and _name_matches(role, item.role)]
        if matched:
            draft.cite("staff", matched)
            draft.satisfied(f"'{role}' 역할 인력 {len(matched)}명 보유{draft.note}")
            return
        if any(item.role for item in staff):
            draft.review(
                f"보유 인력 역할 중 '{role}'과 일치하는 항목 없음 — 명칭 확인 필요",
                ctx.question(requirement),
            )
            return
        draft.insufficient(
            "프로필 인력에 역할 정보가 없어 판정 보류", ctx.question(requirement)
        )
        return

    draft.review(
        "요건에서 등급·경력·인원 조건을 특정하지 못함 — 담당자 확인 필요",
        ctx.question(requirement),
    )


def _required_headcount(requirement: QualificationRequirement, raw: str) -> int:
    if requirement.unit == "PERSON" and isinstance(requirement.value, (int, float)):
        return int(requirement.value)
    normalized = normalize_count(raw)
    if normalized["parse_status"] == "success":
        return int(normalized["value"])
    return 1


def _judge_company_size(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    """Size restrictions, and the group-affiliation condition tangled with them.

    Size is answerable from the core profile. Whether the company belongs to a
    large business group is a separate fact that the profile does not hold, and a
    small company is not evidence of non-affiliation. When both conditions share
    one requirement, the settled half is still reported so the user only has to
    confirm what is actually open.
    """
    view = ctx.view
    text = f"{requirement.raw or ''} {requirement.value or ''}"
    excludes = _SIZE_EXCLUDE_RE.search(text)
    sme_only = _SIZE_REQUIRE_SME_RE.search(text)
    if not (excludes or sme_only):
        draft.review(
            "기업규모 제한의 형식을 특정하지 못함 — 담당자 확인 필요", ctx.question(requirement)
        )
        return

    size = view.company_size
    if not size:
        draft.insufficient(
            "공고가 기업규모를 제한하지만 프로필에 기업규모 정보가 없음",
            "귀사의 기업규모를 알려주시겠어요? (중소기업 / 중견기업 / 대기업)",
        )
        return

    label = SIZE_LABELS.get(size, size)
    size_ok = size == SIZE_SMALL
    size_reason = f"프로필 기업규모 '{label}'" + (
        "이 제한 대상이 아님" if size_ok else "이 제한 대상에 해당"
    )
    draft.cite_values("basic.company_size", [label])

    if not _AFFILIATE_RE.search(text):
        if size_ok:
            draft.satisfied(size_reason)
        else:
            draft.unsatisfied(size_reason)
        return

    if not size_ok:
        # Size alone already settles it; there is no reason to ask further.
        draft.unsatisfied(size_reason)
        return

    affiliation = view.extension_value("conglomerate_affiliate") or {}
    is_affiliate = (
        affiliation.get("is_affiliate") if isinstance(affiliation, dict) else None
    )
    if is_affiliate is not None:
        entry = view.extension_entry("conglomerate_affiliate")
        draft.basis_type = "USER_ANSWER" if entry and entry.source == "askback" else "PROFILE"
        if entry is not None:
            draft.evidence_statuses.append(entry.evidence_status)
        if is_affiliate:
            draft.unsatisfied(f"{size_reason}. 다만 상호출자제한기업집단 계열회사에 해당")
        else:
            draft.satisfied(f"{size_reason}. 상호출자제한기업집단 계열회사에도 해당하지 않음")
        return

    draft.extension_key = "conglomerate_affiliate"
    draft.insufficient(
        f"{size_reason}. 다만 상호출자제한기업집단·계열회사 소속 여부는 "
        f"기업규모와 별개 정보이고 프로필에 없어 확정할 수 없음",
        "귀사가 상호출자제한기업집단(대기업집단) 계열회사에 해당하는지 알려주시겠어요?",
    )


def _judge_industry(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    if not view.has("industry_codes"):
        draft.insufficient("프로필에 업종 정보 없음", ctx.question(requirement))
        return

    target = str(requirement.value or "").strip()
    codes = view.industry_codes
    labels = view.industry_labels

    if target and target in codes:
        draft.cite_values("basic.industry_codes", [target])
        draft.satisfied(f"등록 업종코드 '{target}' 보유")
        return
    matched = [
        label
        for label in labels
        if target and (_name_matches(label, target) or _name_matches(target, label))
    ]
    if matched:
        draft.cite_values("basic.industry_codes", matched)
        draft.satisfied(f"등록 업종 {matched} 일치")
        return
    if codes or labels:
        draft.review(
            f"등록 업종 {labels or codes} 중 요건 업종 '{target}'과 일치하는 항목 없음 — 확인 필요",
            ctx.question(requirement),
        )
        return
    draft.basis_type = "PROFILE"
    draft.unsatisfied("등록 업종 없음(프로필에 빈 목록으로 명시)")


def _judge_experience_field(
    ctx: _Context, requirement: QualificationRequirement, draft: _Draft
) -> None:
    view = ctx.view
    if not view.has("fields") and not view.has("performances"):
        draft.insufficient("프로필에 사업 분야·실적 정보 없음", ctx.question(requirement))
        return

    target = str(requirement.value or "").strip()
    if not target:
        draft.review("요건의 경험 분야를 특정하지 못함 — 확인 불가", ctx.question(requirement))
        return

    declared = list(view.fields)
    from_performances = [
        field_name for item in view.performances for field_name in item.fields
    ]
    pool = declared + from_performances

    matched = [
        name
        for name in pool
        if _name_matches(name, target) or _name_matches(target, name)
    ]
    if matched:
        draft.cite_values("fields", sorted(set(matched)))
        draft.satisfied(f"수행 분야 {sorted(set(matched))}이 요건 '{target}'과 일치")
        return
    if pool:
        draft.review(
            f"보유 분야 {sorted(set(pool))} 중 요건 '{target}'과 일치하는 항목 없음 — 확인 필요",
            ctx.question(requirement),
        )
        return
    draft.basis_type = "PROFILE"
    draft.unsatisfied(f"'{target}' 분야 수행 이력 없음(프로필에 빈 목록으로 명시)")


def _judge_by_extension(
    ctx: _Context,
    requirement: QualificationRequirement,
    draft: _Draft,
    spec: extensions.ExtensionSpec,
) -> None:
    """Judge from a notice-specific field, or ask for exactly that field.

    Approximating with a core field is not an option here — an approximation is a
    judgment without a source behind it.
    """
    draft.extension_key = spec.key
    value = ctx.view.extension_value(spec.key)
    if value is None:
        draft.insufficient(
            f"이 공고는 '{spec.label}'을 요구합니다 — 아직 받지 않은 항목입니다", spec.ask
        )
        return

    entry = ctx.view.extension_entry(spec.key)
    draft.basis_type = "USER_ANSWER" if entry and entry.source == "askback" else "PROFILE"
    if entry is not None:
        draft.evidence_statuses.append(entry.evidence_status)
        draft.profile_refs.append({"section": "extensions", "id": spec.key})

    verdict, reason = spec.judge(value, requirement)
    if verdict == "충족":
        draft.satisfied(f"{reason}{draft.note}")
    elif verdict == "미충족":
        draft.unsatisfied(reason)
    else:
        draft.insufficient(reason, spec.ask)


_RULES: dict[str, Callable[[_Context, QualificationRequirement, _Draft], None]] = {
    "PERFORMANCE_AMOUNT": _judge_performance_amount,
    "PERFORMANCE_COUNT": _judge_performance_count,
    "REGISTRATION_CERTIFICATION": _judge_certification,
    "REGION": _judge_region,
    "STAFF": _judge_staff,
    "COMPANY_SIZE": _judge_company_size,
    "INDUSTRY": _judge_industry,
    "EXPERIENCE_FIELD": _judge_experience_field,
}


def judge_requirement(
    requirement: QualificationRequirement,
    profile: Any,
    *,
    preflight_case_id: str,
    question_writer: QuestionWriter | None = None,
    today: date | None = None,
    rule_version: str = RULE_VERSION,
) -> Judgment:
    """Judge one canonical requirement against one company profile."""
    ctx = _Context(
        view=as_profile_view(profile),
        today=today or date.today(),
        question_writer=question_writer,
    )
    draft = _Draft()

    # An empty profile is not short-circuited here. Every rule already reports
    # precisely which section it was missing, which is more useful than one
    # generic "no profile" line, and some requirements ("참가 지역 제한 없음") are
    # decidable with no profile at all. A caller that wants to prompt for the
    # whole profile can test `as_profile_view(profile)` for emptiness itself.
    #
    # An extension that owns this requirement is consulted before any core rule,
    # so the core never approximates an industry-specific condition.
    spec = extensions.spec_for_requirement(requirement)
    if spec is not None:
        _judge_by_extension(ctx, requirement, draft, spec)
    else:
        rule = _RULES.get(requirement.type)
        if rule is None:
            draft.unsupported("자동 판정 미지원 유형 — 담당자 확인 필요", ctx.question(requirement))
        else:
            rule(ctx, requirement, draft)

    evidence_held = bool(draft.evidence_statuses) and all(
        status == EVIDENCE_VERIFIED for status in draft.evidence_statuses
    )
    return Judgment(
        judgment_key=f"JDG-{preflight_case_id}-{requirement.requirement_key}",
        preflight_case_id=preflight_case_id,
        notice_version_id=requirement.notice_version_id,
        requirement_key=requirement.requirement_key,
        status=draft.status,
        basis_type=draft.basis_type,
        evidence_held=evidence_held,
        reason_code=draft.reason_code,
        # A satisfied judgment resting on unchecked paperwork still needs the
        # document before submission, and that has to be visible.
        requires_evidence=draft.status == "SATISFIED" and not evidence_held,
        profile_refs=draft.profile_refs,
        requirement_evidence_keys=list(requirement.evidence_keys),
        rule_version=rule_version,
        reason=draft.reason,
        follow_up_question=draft.question,
        required_extension_key=draft.extension_key,
    )


def judge_requirements(
    requirements: list[QualificationRequirement],
    profile: Any,
    *,
    preflight_case_id: str,
    question_writer: QuestionWriter | None = None,
    today: date | None = None,
    rule_version: str = RULE_VERSION,
) -> list[Judgment]:
    """Judge every requirement of one notice version against one profile."""
    return [
        judge_requirement(
            requirement,
            profile,
            preflight_case_id=preflight_case_id,
            question_writer=question_writer,
            today=today,
            rule_version=rule_version,
        )
        for requirement in requirements
    ]


def judge_analysis_result(
    result: RequirementAnalysisResult,
    profile: Any,
    *,
    preflight_case_id: str,
    question_writer: QuestionWriter | None = None,
    today: date | None = None,
    rule_version: str = RULE_VERSION,
) -> list[Judgment]:
    """Judge the requirements produced by `analyze_qualification_documents`."""
    return judge_requirements(
        result.requirements,
        profile,
        preflight_case_id=preflight_case_id,
        question_writer=question_writer,
        today=today,
        rule_version=rule_version,
    )
