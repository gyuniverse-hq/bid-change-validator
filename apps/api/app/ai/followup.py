"""Follow-up answers: turning what a bidding officer says back into profile fields.

`app.ai.judgment` stops at UNKNOWN and asks a question. This module closes that
loop by reading the answer and proposing a profile update, so the same
deterministic rules can run again with more information.

The role split is identical to requirement extraction:

- The model turns prose into fields and nothing else. It copies "6억 1천만원" as a
  string; it never converts it to a number.
- Numbers and dates are converted here, in code.
- Nothing in this module judges. Whether a requirement is met stays with
  `app.ai.judgment`.
- Structured Outputs blocks schema drift at decode time.

Hallucination control matters more here than anywhere else in the pipeline. If an
officer answers "네, 있습니다" and the model supplies an amount, that invented
number flows straight into a SATISFIED judgment. So **every field carrying a
number is checked against the answer text** and dropped when it does not appear.

Notice-specific extensions never reach the model at all. An answer shaped like
"특급 2명, 고급 3명" is read more accurately, and far more cheaply, by the parser in
`app.ai.extensions`. The model is for free prose only.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import extensions
from .contracts import QualificationRequirement
from .normalization import normalize_count, normalize_value
from .profile import (
    EVIDENCE_DECLARED,
    Certification,
    CompanyProfileSnapshot,
    ExtensionValue,
    Performance,
    ProfileField,
    StaffMember,
    as_profile_view,
)
from .requirement_extraction import StructuredExtractor


AnswerType = Literal[
    "ANSWERED",  # the officer supplied values
    "NONE_HELD",  # the officer stated the company has none
    "UNKNOWN",  # the officer has to check first
    "IRRELEVANT",  # the answer did not address the question
    "PARSER_UNAVAILABLE",  # no structured extractor was supplied
    "FAILED",  # the extractor raised
]

# The prompt speaks Korean because the answers do; the values are mapped onto the
# contract vocabulary on the way out so no caller has to match Korean strings.
_ANSWER_TYPE_BY_LABEL = {
    "제공": "ANSWERED",
    "해당없음": "NONE_HELD",
    "모름": "UNKNOWN",
    "무관": "IRRELEVANT",
}

# Requirement types whose "we have none" answer can be stored as an explicit
# empty section. Stating none is a real answer and makes the requirement
# judgeable; leaving the section unset would keep asking forever.
_NONE_HELD_SECTIONS = {
    "PERFORMANCE_AMOUNT": "performances",
    "PERFORMANCE_COUNT": "performances",
    "REGISTRATION_CERTIFICATION": "certifications",
    "STAFF": "staff",
}

ANSWER_SCHEMA: dict[str, Any] = {
    "name": "followup_answer",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer_type": {
                "type": "string",
                "enum": ["제공", "해당없음", "모름", "무관"],
                "description": (
                    "제공=값을 알려줌, 해당없음=없다고 답함, "
                    "모름=확인이 필요하다고 답함, 무관=질문과 무관한 답변"
                ),
            },
            "certifications": {
                "type": "array",
                "description": "보유한 인증·면허·등록 명칭",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string", "description": "명칭 원문 그대로"},
                        "issued_year_raw": {
                            "type": ["string", "null"],
                            "description": "취득 연도 원문. 없으면 null",
                        },
                    },
                    "required": ["label", "issued_year_raw"],
                },
            },
            "region_label": {
                "type": ["string", "null"],
                "description": "소재지 원문 그대로. 예: '서울 강남구'",
            },
            "performances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": ["string", "null"]},
                        "client_type": {
                            "type": ["string", "null"],
                            "enum": ["public", "private", None],
                            "description": (
                                "발주처가 공공이라고 답변에 나오면 public, 민간이면 private, "
                                "안 나오면 null"
                            ),
                        },
                        "amount_raw": {
                            "type": ["string", "null"],
                            "description": (
                                "금액 원문 그대로. 예: '6억 1천만원'. 숫자로 바꾸지 마라"
                            ),
                        },
                        "done_raw": {
                            "type": ["string", "null"],
                            "description": "완료 시점 원문 그대로. 예: '작년 8월', '2024-08-30'",
                        },
                    },
                    "required": ["title", "client_type", "amount_raw", "done_raw"],
                },
            },
            "staff": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "role": {
                            "type": ["string", "null"],
                            "description": "역할 원문. 예: 'PM', '개발자'. 없으면 null",
                        },
                        "career_years_raw": {
                            "type": ["string", "null"],
                            "description": "경력 연수 원문. 예: '7년'. 숫자로 바꾸지 마라",
                        },
                        "grade_raw": {
                            "type": ["string", "null"],
                            "description": (
                                "특급/고급/중급/초급 등급 표현이 답변에 있으면 그대로. 없으면 null"
                            ),
                        },
                        "count_raw": {
                            "type": ["string", "null"],
                            "description": "인원 수 원문. 예: '3명'. 없으면 null",
                        },
                    },
                    "required": ["role", "career_years_raw", "grade_raw", "count_raw"],
                },
            },
        },
        "required": [
            "answer_type",
            "certifications",
            "region_label",
            "performances",
            "staff",
        ],
    },
}

SYSTEM_PROMPT = """너는 입찰 담당자의 답변을 회사 프로필 필드로 옮겨 적는 도구다. 규칙:
1. 답변에 **실제로 적힌 내용만** 옮긴다. 추측하거나 값을 지어내지 마라.
2. 금액·기간·인원·경력은 **원문 문자열 그대로** 담는다. 숫자로 변환하지 마라.
   ("6억 1천만원"을 610000000으로 바꾸지 마라)
3. 담당자가 "없다"고 하면 answer_type=해당없음, 값 배열은 비운다.
4. "모르겠다/확인해보겠다"면 answer_type=모름, 값 배열은 비운다.
5. 질문과 상관없는 답변이면 answer_type=무관.
6. 판정하지 마라. 요건을 충족하는지 여부는 네가 결정할 일이 아니다."""


class ProfileUpdate(BaseModel):
    """A proposed change to the company profile.

    None means "this answer said nothing about the section"; an empty list means
    "the officer stated there are none", which is a usable answer. Collapsing the
    two would either lose the statement or invent one.
    """

    performances: list[Performance] | None = None
    certifications: list[Certification] | None = None
    staff: list[StaffMember] | None = None
    region: ProfileField | None = None
    extensions: dict[str, ExtensionValue] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return (
            self.performances is None
            and self.certifications is None
            and self.staff is None
            and self.region is None
            and not self.extensions
        )


class FollowUpResult(BaseModel):
    """What one follow-up answer produced, including what was thrown away."""

    answer_type: AnswerType
    updates: ProfileUpdate = Field(default_factory=ProfileUpdate)
    # Discarded items with the reason. Silent drops hide the model inventing
    # values, which is exactly what has to stay visible.
    rejected: list[str] = Field(default_factory=list)
    notes: str = ""


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _appears_in(value: str | None, answer_text: str) -> bool:
    """Is a number-bearing value actually present in what the officer wrote?"""
    return bool(value) and _squash(value) in _squash(answer_text)


def _loosely_appears(value: str | None, answer_text: str) -> bool:
    """Looser check for names, which the model tends to tidy up.

    An officer writing "ISO 27001" may come back as "ISO/IEC 27001", so an exact
    match is too strict. Matching on any single token is too loose in the other
    direction: "ISO 9001" would then pass against an answer mentioning only
    ISO 27001, because they share the "ISO" token.

    So when a name carries digits, the digits are its identity and at least one
    of them has to appear. Purely alphabetic names fall back to any token.
    """
    if not value:
        return False
    squashed = _squash(answer_text)
    tokens = [token for token in re.split(r"[^0-9A-Za-z가-힣]+", value) if len(token) >= 2]
    if not tokens:
        return _squash(value) in squashed
    digit_tokens = [token for token in tokens if token.isdigit()]
    if digit_tokens:
        return any(token in squashed for token in digit_tokens)
    return any(
        token in squashed or token.lower() in squashed.lower() for token in tokens
    )


_RELATIVE_YEAR = {"올해": 0, "금년": 0, "작년": -1, "지난해": -1, "재작년": -2}


def parse_date_raw(raw: str | None, *, today: date | None = None) -> date | None:
    """Read a completion date out of source wording. None when it does not parse.

    Date conversion is code, not model output, for the same reason numbers are.
    An unparseable date returns None so the caller drops the row rather than
    placing it in an arbitrary year.
    """
    if not raw:
        return None
    today = today or date.today()
    text = raw.strip()

    match = re.search(r"(\d{4})[-.\/년]\s*(\d{1,2})[-.\/월]\s*(\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = re.search(r"(\d{4})[-.\/년]\s*(\d{1,2})\s*월?", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return date(year, month, 28)  # day unknown, kept near month end

    # Longest first: "재작년" contains "작년", and matching the shorter one would
    # silently place the project one year too late.
    for word, delta in sorted(_RELATIVE_YEAR.items(), key=lambda item: -len(item[0])):
        if word in text:
            month_match = re.search(r"(\d{1,2})\s*월", text)
            month = (
                int(month_match.group(1))
                if month_match and 1 <= int(month_match.group(1)) <= 12
                else 12
            )
            return date(today.year + delta, month, 28)

    match = re.fullmatch(r"\s*(\d{4})\s*년?\s*", text)
    if match:
        return date(int(match.group(1)), 12, 28)
    return None


def _next_id(existing: list[Any], prefix: str) -> str:
    """Continue the pf_01 / st_03 numbering already in the profile."""
    numbers = []
    for item in existing:
        match = re.fullmatch(rf"{prefix}_(\d+)", str(getattr(item, "id", "") or ""))
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}_{(max(numbers) + 1) if numbers else 1:02d}"


def _read_performances(
    rows: list[dict[str, Any]],
    *,
    answer_text: str,
    existing: list[Performance],
    rejected: list[str],
    today: date | None,
) -> list[Performance]:
    accepted: list[Performance] = []
    for row in rows:
        amount_raw = row.get("amount_raw")
        if amount_raw and not _appears_in(amount_raw, answer_text):
            rejected.append(f"실적 금액 '{amount_raw}' — 답변 원문에 없음(환각 의심)")
            continue
        if not amount_raw:
            rejected.append("실적 금액이 답변에 없음 — 판정 보류 유지")
            continue

        done_raw = row.get("done_raw")
        if done_raw and not _appears_in(done_raw, answer_text):
            rejected.append(f"실적 완료 시점 '{done_raw}' — 답변 원문에 없음(환각 의심)")
            done_raw = None

        normalized = normalize_value(amount_raw)
        if normalized["parse_status"] != "success" or normalized.get("value") is None:
            rejected.append(f"실적 금액 '{amount_raw}' 정규화 실패 — 반영하지 않음")
            continue

        completed = parse_date_raw(done_raw, today=today)
        if completed is None:
            rejected.append(f"실적 완료 시점 '{done_raw}' 해석 불가 — 최근 실적 판정 불가")
            continue

        client_type = row.get("client_type")
        if client_type not in ("public", "private"):
            client_type = None

        accepted.append(
            Performance(
                id=_next_id(existing + accepted, "pf"),
                title=row.get("title") or "(담당자 답변)",
                amount=normalized["value"],
                year=completed.year,  # the profile stores a year, not a date
                client_type=client_type,
                source="askback",
                evidence_status=EVIDENCE_DECLARED,
            )
        )
    return accepted


def _read_certifications(
    rows: list[dict[str, Any]],
    *,
    answer_text: str,
    rejected: list[str],
    today: date | None,
) -> list[Certification]:
    accepted: list[Certification] = []
    for row in rows:
        label = (row.get("label") or "").strip()
        if not label:
            continue
        if not _loosely_appears(label, answer_text):
            rejected.append(f"인증·면허 '{label}' — 답변 원문과 대응 안 됨(환각 의심)")
            continue

        year_raw = row.get("issued_year_raw")
        issued_year = None
        if year_raw:
            if _appears_in(year_raw, answer_text):
                parsed = parse_date_raw(year_raw, today=today)
                issued_year = parsed.year if parsed else None
            else:
                rejected.append(f"인증 취득연도 '{year_raw}' — 답변 원문에 없음(환각 의심)")

        accepted.append(
            Certification(
                label=label,
                issued_year=issued_year,
                source="askback",
                evidence_status=EVIDENCE_DECLARED,
            )
        )
    return accepted


def _read_staff(
    rows: list[dict[str, Any]],
    *,
    answer_text: str,
    existing: list[StaffMember],
    rejected: list[str],
) -> list[StaffMember]:
    accepted: list[StaffMember] = []
    for row in rows:
        grade_raw = row.get("grade_raw")
        career_raw = row.get("career_years_raw")
        count_raw = row.get("count_raw")

        if grade_raw and not career_raw:
            # The core staff section has no grade field on purpose. Say why
            # instead of dropping the answer silently.
            rejected.append(
                f"인력 등급 '{grade_raw}' — 코어 인력 항목에는 등급 필드가 없습니다. "
                f"등급을 요구하는 공고라면 '소프트웨어기술자 등급별 인원' 추가 항목으로 "
                f"받아야 하고, 그 외에는 경력 연수로 답변이 필요합니다"
            )
            continue
        if not career_raw:
            continue
        if not _appears_in(career_raw, answer_text):
            rejected.append(f"인력 경력 '{career_raw}' — 답변 원문에 없음(환각 의심)")
            continue

        normalized = normalize_value(career_raw)
        years = (
            normalized.get("value") if normalized.get("parse_status") == "success" else None
        )
        if years is None:
            rejected.append(f"인력 경력 '{career_raw}' 정규화 실패 — 반영하지 않음")
            continue
        if normalized.get("unit") == "MONTH":
            years = years / 12.0  # periods normalize to months

        headcount = 1
        if count_raw and _appears_in(count_raw, answer_text):
            counted = normalize_count(count_raw)
            if counted["parse_status"] == "success":
                headcount = int(counted["value"])

        for _ in range(max(headcount, 0)):
            accepted.append(
                StaffMember(
                    id=_next_id(existing + accepted, "st"),
                    role=row.get("role"),
                    career_years=round(years, 1),
                    source="askback",
                    evidence_status=EVIDENCE_DECLARED,
                )
            )
    return accepted


def parse_followup_answer(
    requirement: QualificationRequirement,
    question: str,
    answer_text: str,
    *,
    profile: Any = None,
    structured_extract: StructuredExtractor | None = None,
    today: date | None = None,
) -> FollowUpResult:
    """Read one follow-up answer into a proposed profile update.

    `profile` is only used to continue existing id numbering; nothing is merged
    here. Applying the update is a separate, explicit step.
    """
    view = as_profile_view(profile)

    # A notice-specific extension is read in code. The answer shape is fixed, so
    # a model would add cost and a hallucination surface for nothing.
    spec = extensions.spec_for_requirement(requirement)
    if spec is not None:
        value = extensions.parse_answer_for(spec.key, answer_text)
        if value is None:
            return FollowUpResult(
                answer_type="UNKNOWN",
                rejected=[
                    f"'{spec.label}' 답변에서 값을 읽지 못했습니다 (예: {spec.input_hint})"
                ],
            )
        return FollowUpResult(
            answer_type="ANSWERED",
            updates=ProfileUpdate(
                extensions={
                    spec.key: ExtensionValue(
                        value=value,
                        label=spec.label,
                        source="askback",
                        evidence_status=EVIDENCE_DECLARED,
                    )
                }
            ),
        )

    if structured_extract is None:
        return FollowUpResult(
            answer_type="PARSER_UNAVAILABLE",
            notes="구조화 추출기가 주입되지 않아 자유 서술 답변을 해석할 수 없습니다.",
        )

    user_body = (
        f"[확인하려는 요건]\n{requirement.raw}\n\n"
        f"[담당자에게 한 질문]\n{question}\n\n"
        f"[담당자의 답변]\n{answer_text}"
    )
    try:
        extracted = structured_extract(SYSTEM_PROMPT, user_body, ANSWER_SCHEMA)
    except Exception as error:  # noqa: BLE001 - surfaced to the caller as a result
        return FollowUpResult(answer_type="FAILED", notes=f"답변 해석 호출 실패: {error}")

    answer_type = _ANSWER_TYPE_BY_LABEL.get(
        str(extracted.get("answer_type") or ""), "IRRELEVANT"
    )
    rejected: list[str] = []

    performances = _read_performances(
        list(extracted.get("performances") or []),
        answer_text=answer_text,
        existing=view.performances,
        rejected=rejected,
        today=today,
    )
    certifications = _read_certifications(
        list(extracted.get("certifications") or []),
        answer_text=answer_text,
        rejected=rejected,
        today=today,
    )
    staff = _read_staff(
        list(extracted.get("staff") or []),
        answer_text=answer_text,
        existing=view.staff,
        rejected=rejected,
    )

    update = ProfileUpdate()
    if performances:
        update.performances = performances
    if certifications:
        update.certifications = certifications
    if staff:
        update.staff = staff

    # "우리는 없습니다" is an answer, not a gap. Recording it as an explicit empty
    # section is what lets the next judgment settle instead of asking again.
    if answer_type == "NONE_HELD":
        section = _NONE_HELD_SECTIONS.get(requirement.type)
        if section is not None and getattr(update, section) is None:
            setattr(update, section, [])

    region = extracted.get("region_label")
    if region:
        if _loosely_appears(region, answer_text):
            # An officer's answer cannot tell us the administrative code, so only
            # the label is filled in.
            update.region = ProfileField(value=None, label=region, source="askback")
        else:
            rejected.append(f"소재지 '{region}' — 답변 원문과 대응 안 됨(환각 의심)")

    return FollowUpResult(answer_type=answer_type, updates=update, rejected=rejected)


def apply_profile_update(profile: Any, update: ProfileUpdate) -> CompanyProfileSnapshot:
    """Merge a proposed update and return a new snapshot; the input is untouched.

    Performances and staff accumulate, because projects and people add up.
    Certifications are a union by name so re-answering does not duplicate them.
    Basic fields and extension entries are replaced, because the latest answer to
    the same question is the one that counts.
    """
    view = as_profile_view(profile)
    merged = view.snapshot.model_copy(deep=True)

    if update.performances is not None:
        merged.performances = (
            list(merged.performances or []) + list(update.performances)
            if update.performances
            else []
        )
    if update.staff is not None:
        merged.staff = (
            list(merged.staff or []) + list(update.staff) if update.staff else []
        )
    if update.certifications is not None:
        if update.certifications:
            existing = list(merged.certifications or [])
            held = {(item.label or item.code) for item in existing}
            merged.certifications = existing + [
                item for item in update.certifications if (item.label or item.code) not in held
            ]
        else:
            merged.certifications = []
    if update.region is not None:
        merged.basic.region = update.region
    if update.extensions:
        merged.extensions = {**merged.extensions, **update.extensions}

    return merged
