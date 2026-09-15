"""나라장터 절차와 회사 자격조건을 구분한다. 혼합 원문 전체를 제거하지 않는다.

절차 분류는 충족·면제 판정이 아니다. 확인할 사실과 원문을 경고 진단으로 남기며,
공통 clause_safety나 기존 판정기의 의미는 바꾸지 않는다.
"""
from __future__ import annotations

import re
import unicodedata

PROCEDURE_VERSION = 'qualification-procedural-facts-v1'
_PLATFORM = r'(?:국가종합전자조달시스템|나라장터|G2B|전자입찰시스템)'
_ACTION = r'(?:입찰\s*참가\s*자격\s*등록|입찰\s*참가\s*등록|(?:전자입찰\s*)?이용자\s*등록)'
_MENTION = re.compile(_PLATFORM + r'.{0,80}?' + _ACTION + r'|' + _PLATFORM + r'\s*에\s*등록|입찰\s*참가\s*자격\s*등록\s*규정', re.I)
_PURE = re.compile(r'(?:' + _PLATFORM + r'(?:의|에)?)?(?:입찰참가자격등록(?:규정)?|입찰참가등록|전자입찰이용자등록|이용자등록)(?:완료|업체)?', re.I)


def procedure_mentions(raw: str, registration_name: str = '') -> list[str]:
    text = ' '.join((raw + ' ' + registration_name).split())
    return list(dict.fromkeys(m.group(0) for m in _MENTION.finditer(text)))


def is_procedure_name(name: str, raw: str) -> bool:
    value = re.sub(r'\s+|[「」『』()]', '', unicodedata.normalize('NFKC', name))
    return bool(value and procedure_mentions(raw, name) and (_PURE.fullmatch(value)
        or re.fullmatch(_PLATFORM + r'(?:등록)?', value, re.I)))


def procedure_diagnostic(raw: str, mentions: list[str]) -> dict:
    return {'code': 'PROCEDURAL_REQUIREMENT_REVIEW', 'raw': raw,
            'procedure_kind': 'G2B_REGISTRATION', 'source_expressions': mentions,
            'verification_status': 'NOT_CHECKED', 'procedure_version': PROCEDURE_VERSION,
            'reason': '일반 회사 인증 목록으로 판정하지 않습니다. 이번 입찰의 등록 절차·시점을 확인해야 합니다.'}
