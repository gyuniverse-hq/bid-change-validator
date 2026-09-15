"""한 조항 안에 명시된 업종명/등록행위 ↔ 단일 업종코드 연결만 확인한다.

같은 청크, 한글 인증명, 코드의 존재만으로 동일 사실을 추정하지 않는다.
여러 업종명·코드·발급기관·관계가 있으면 호출자가 별개 조건으로 보존한다.
"""
from __future__ import annotations

import re
import unicodedata
from ....qualification.rules.clause_safety import unsafe_clause_reason

_CODE = re.compile(r'업종\s*코드\s*[:：]?\s*(?P<labelled>[0-9]{4})(?![0-9])'
                   r'|[가-힣·ㆍ]+업\s*\(\s*(?P<named>[0-9]{4})\s*\)')
_NAME = re.compile(r'([가-힣·ㆍ]+업)(?=\s|\(|$|등록|신고|허가)')
_VALUE = re.compile(r'(?P<name>[가-힣·ㆍ]+업)(?:등록|신고|허가)?(?:업체|업자)?')
_ACTS = frozenset({'등록', '신고', '영업신고', '허가', '인허가'})
_LABEL = r'업종\s*코드\s*[:：]?\s*([0-9]{4})(?![0-9])'


def _name(value: str) -> str:
    return re.sub(r'\s+|[·ㆍ]', '', unicodedata.normalize('NFKC', value))


def registration_alias_code(value: str, raw: str) -> str | None:
    if not isinstance(value, str) or not isinstance(raw, str) or unsafe_clause_reason(raw):
        return None
    val = _name(value)
    match = _VALUE.fullmatch(val)
    if val not in _ACTS and not match:
        return None
    codes = {m['labelled'] or m['named'] for m in _CODE.finditer(raw)}
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    names = {_name(m[1]) for m in _NAME.finditer(raw)} - {'영업', '등록업'}
    if len(names) > 1:
        return None
    if match and val not in _ACTS:
        name = match['name']
        if names != {name}:
            return None
        # 단일 업종명과 단일 코드의 명시적 표기 또는 영업신고(업종코드) 연결.
        compact = _name(raw)
        direct = re.search(re.escape(name) + r'(?:등록|신고|허가)?\((?:업종코드[:：]?)?' + code + r'\)', compact)
        if direct or (not re.search(r'및|그리고|별도|추가|각각', raw)
                and re.search(r'(?:영업신고|인허가|허가)\s*\(\s*' + _LABEL, raw)):
            return code
        return None
    # 일반 '허가'는 아무 업종에 합치지 않는다. 해당 행위와 코드가 바로 연결돼야 한다.
    compact = _name(raw)
    if re.search(re.escape(val) + r'\(업종코드[:：]?' + code + r'\)', compact):
        return code
    if val in {'등록', '신고'} and re.search(r'업종코드[:：]?' + code + re.escape(val), compact):
        return code
    return None
