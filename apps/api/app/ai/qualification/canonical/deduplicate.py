"""같은 조항에서 나온 요건이 겹칠 때 정리한다.

[재현 2026-09-14] 모델의 유형 분류는 실행마다 흔들린다. 구내식당 공고(R26BK01633750)의
「나. 식품위생법에 의거 단체급식업 등록업체…영업신고(업종코드 : 1450)…」 한 조항이
실행에 따라 이렇게 나왔다.

    run0   REGISTRATION_CERTIFICATION "단체급식업등록"  +  INDUSTRY "1450"   <- 둘 다
    run1   INDUSTRY "1450"
    run2   REGISTRATION_CERTIFICATION 두 개
    이전   기타요건 (통째로 버려짐)

둘 다 나온 실행이 위험하다. 두 요건은 ALL_OF 묶음이라 **둘 다 충족해야** 하는데,
업종 1450 을 실제로 보유한 회사에 대보면

    INDUSTRY 1450                      -> SATISFIED
    REGISTRATION_CERTIFICATION 단체급식업등록 -> UNSATISFIED   <- 틀린 미달

같은 사실인데 하나는 회사의 업종 목록에서 찾고 하나는 인증 목록에서 찾는다. 자격 있는
회사가 떨어진다 — 이 기능에서 가장 나쁜 실패다.

무엇을 정리하고 무엇을 두는가
-----------------------------
겹친다고 아무거나 합치면 진짜 요건을 잃는다. 한 조항이 "전북특별자치도에 있고 업종
1257 을 등록한 업체" 처럼 서로 다른 두 요건을 정말로 담을 수도 있다. 그래서 둘만 한다.

1. **완전 중복** — 유형·값·원문이 같으면 하나만 남긴다. 잃는 것이 없다.
2. **업종 등록 ↔ 등록·인증 보유 혼동** — 프롬프트가 "혼동하지 마라" 라고 적어 둔 바로 그
   쌍이다. 짧은 원문이 긴 원문 안에 들어 있고, 긴 쪽이 업종코드를 갖고 있고, 짧은 쪽의
   값이 긴 원문 안에 글자 그대로 있을 때만 짧은 쪽을 접는다. 세 조건이 다 맞으면 같은
   사실을 두 이름으로 부른 것이다.

지역·규모·인력처럼 다른 유형끼리는 손대지 않는다. 겹쳐 보여도 정말 둘 다 필요한
요건일 수 있고, 잘못 접으면 있어야 할 판정이 사라진다.
"""

from __future__ import annotations

import re
import unicodedata

from ...contracts import QualificationRequirement


_INDUSTRY_CODE_VALUE_RE = re.compile(r"^[0-9]{4}$|^[0-9]{10}$")

# 접히는 쪽의 값이 업종명 그 자체여야 한다. 한글로만 이루어지고 "…업" 으로 끝나거나
# 그 뒤에 등록·신고·허가가 붙은 모양. 숫자나 로마자가 섞이면 인증 규격 이름이다
# (ISO 9001, KS 27001). 그런 것은 별개 요건이므로 접지 않는다.
_INDUSTRY_NAME_VALUE_RE = re.compile(r"[가-힣·ㆍ]{2,}업(?:등록|신고|허가|업체)?")


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))


def _identity(requirement: QualificationRequirement) -> tuple[str, str, str]:
    return requirement.type, _norm(requirement.value), _norm(requirement.raw)


def _has_closed_identifier(requirement: QualificationRequirement) -> bool:
    return bool(_INDUSTRY_CODE_VALUE_RE.match(_norm(requirement.value)))


def _folds_into(
    candidate: QualificationRequirement, keeper: QualificationRequirement
) -> bool:
    """candidate 가 keeper 와 같은 사실을 다른 이름으로 부른 것인가.

    접히는 값이 **업종명 그 자체**일 때만 인정한다. "단체급식업등록" 은 업종 1450 을
    말을 바꿔 부른 것이지만, 같은 조항에 적힌 "ISO 9001" 은 별개의 인증 요건이다.
    이 구분이 없으면 진짜 인증 요건을 삼킨다 — 실제로 첫 판에서 그랬다.
    """
    if candidate.type != "REGISTRATION_CERTIFICATION" or keeper.type != "INDUSTRY":
        return False
    if not _has_closed_identifier(keeper):
        return False
    value = _norm(candidate.value)
    if not _INDUSTRY_NAME_VALUE_RE.fullmatch(value):
        return False
    candidate_raw, keeper_raw = _norm(candidate.raw), _norm(keeper.raw)
    if not candidate_raw or candidate_raw not in keeper_raw:
        return False
    return value in keeper_raw


def deduplicate_requirements(
    requirements: list[QualificationRequirement],
) -> tuple[list[QualificationRequirement], list[dict[str, object]]]:
    """겹친 요건을 정리하고, 접은 것은 진단으로 남긴다."""
    kept: list[QualificationRequirement] = []
    diagnostics: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    for requirement in requirements:
        identity = _identity(requirement)
        if identity in seen:
            diagnostics.append({
                "code": "DUPLICATE_REQUIREMENT",
                "raw": requirement.raw,
                "type": requirement.type,
                "value": requirement.value,
                "dropped_key": requirement.requirement_key,
            })
            continue
        seen.add(identity)
        kept.append(requirement)

    folded: list[QualificationRequirement] = []
    for requirement in kept:
        keeper = next(
            (
                other
                for other in kept
                if other is not requirement and _folds_into(requirement, other)
            ),
            None,
        )
        if keeper is None:
            folded.append(requirement)
            continue
        diagnostics.append({
            "code": "MERGED_INDUSTRY_REGISTRATION",
            "raw": requirement.raw,
            "dropped_key": requirement.requirement_key,
            "dropped_value": requirement.value,
            "kept_key": keeper.requirement_key,
            "kept_value": keeper.value,
        })

    return folded, diagnostics
