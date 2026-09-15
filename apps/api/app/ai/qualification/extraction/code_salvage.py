"""모델이 빠뜨린 업종코드 조항을 코드가 원문에서 직접 채운다.

왜
--
같은 공고를 반복해 돌리면 모델이 어떤 실행에서는 업종 조항을 아예 안 올린다.
실측(2026-09-15) —

    구내식당   3회 중 1회  "영업신고(업종코드 : 1450)" 슬롯 없음
    남원글로컬 3회 중 1회  "(1257) 또는 (6770) 또는 (6786)" 조항 통째로 없음

둘 다 원문에 업종코드가 박혀 있다. 모델이 뭐라고 하든 그 숫자는 실행마다 달라지지
않는다. 그러니 모델이 빠뜨린 코드를 코드가 채운다 — 판정은 코드, 서술은 모델이라는 원칙의
추출판이다. LLM 호출은 없다.

무엇을 채우고 무엇을 안 채우나
------------------------------
선별된 청크에서 업종 맥락의 코드("업종코드 : 1450", "폐기물수집·운반업(1227)")를 찾는다.
모델 슬롯 중 어느 것도 그 코드를 담고 있지 않으면, 코드가 든 조항 줄을 그대로 raw 로 하는
업종요건 슬롯을 만든다. 원문을 그대로 쓰므로 근거 검증은 자명하게 통과한다.

안전 가드와 매핑은 그대로 거친다. "A 또는 B" 는 ANY_OF 로, 예외·부정이 붙은 조항은
UNMAPPED 로 — 코드가 채운 슬롯이라고 특별 취급하지 않는다. 채운 슬롯에는 표시를 남긴다.
모델이 왜 빠뜨렸는지는 여기서 알 수 없지만, 빠뜨렸다는 사실은 남아야 한다.
"""

from __future__ import annotations

import re
from typing import Any

# 업종 맥락의 코드만 잡는다. 네 자리 숫자 전부를 코드로 보면 연도·금액·전화번호가 걸린다.
_CODE_IN_CONTEXT_RE = re.compile(
    r"업종\s*코드\s*[:：]?\s*(?P<labelled>[0-9]{4})(?![0-9])"
    r"|[가-힣·ㆍ]{2,}업\s*\(\s*(?P<named>[0-9]{4})\s*\)"
)
# 항목 기호. 괄호 숫자는 (1)·(2) 처럼 한두 자리만이다 — "(6770)" 은 업종코드가 줄머리에 온
# 것이지 새 항목이 아니다. 실제 공고에서 "…폐기물중간재활용업\n(6770)또는…" 로 줄이 바뀌어
# 있었고, 네 자리를 항목으로 보면 '또는' 조항이 두 동강 나서 ANY_OF 를 못 푼다.
_ITEM_MARKER_RE = re.compile(
    r"^\s*(?:제\s*\d+\s*(?:조|장)|\d+(?:\.\d+)*\s*[.)]|[가-힣]\s*[.)]|\(\s*\d{1,2}\s*\)|[○●◦▶▷□■])\s*\S"
)
# 단서·부연 줄. 코드 조항의 raw 에는 넣지 않는다 — "※ 단, 처분 또는 재활용업 허가를…" 이
# 붙으면 '단'·'또는' 때문에 안전 가드가 막아서 정작 코드 요건이 사라진다. 판정은 "회사가
# 그 업종을 등록했는가" 이고 단서는 사람이 읽을 맥락이다. 근거(evidence)는 청크 전체를
# 가리키므로 단서는 거기에 남는다.
_CONTINUATION_RE = re.compile(r"^\s*(?:[※＊*·•\-–—]|☞)\s*\S")


def industry_codes_in(text: str) -> set[str]:
    return {
        match.group("labelled") or match.group("named")
        for match in _CODE_IN_CONTEXT_RE.finditer(text or "")
    }


def _clauses(chunk_text: str) -> list[str]:
    """청크를 항목 줄로 나눈다. 줄바꿈으로 끊긴 문장은 앞 항목에 붙이고, 단서 줄은 뺀다."""
    clauses: list[str] = []
    for line in (chunk_text or "").splitlines():
        if not line.strip():
            continue
        if _CONTINUATION_RE.match(line):
            continue  # 단서 줄은 코드 조항에 안 붙인다 (위 주석)
        if _ITEM_MARKER_RE.match(line) or not clauses:
            clauses.append(line.strip())
        else:
            clauses[-1] += "\n" + line.strip()  # 줄바꿈으로 끊긴 같은 문장
    return clauses


def salvage_missing_industry_slots(
    covered_codes: set[str],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """`covered_codes` 에 없는 업종코드를 원문 조항으로 채운 슬롯 목록을 낸다.

    덮임의 기준은 **요건으로 도달했는가**이지 모델이 냈는가가 아니다. 실측(2026-09-15)에서
    모델이 "○ … 1) A(1257) 또는 B(6770) 또는 C(6786) 등록업체 2) D(1227) 등록업체" 문단을
    통째로 한 슬롯에 담았고, 마지막 조각에 코드가 둘이라 ANY_OF 로 못 풀려 UNMAPPED 가 됐다.
    모델 슬롯의 raw 만 보고 "덮였다" 고 하면 그 네 코드는 영영 안 채워진다. 그래서
    canonical 을 거친 뒤 실제로 요건이 된 코드를 받아 나머지를 채운다.
    """
    covered = set(covered_codes)
    salvaged: list[dict[str, Any]] = []
    seen_raw: set[str] = set()
    for chunk in chunks:
        for clause in _clauses(chunk.get("text") or ""):
            codes = industry_codes_in(clause)
            missing = codes - covered
            if not missing:
                continue
            key = re.sub(r"\s+", "", clause)
            if key in seen_raw:
                continue  # 공고문·제안요청서에 같은 조항이 두 벌이면 한 번만
            seen_raw.add(key)
            salvaged.append({
                "유형": "업종요건",
                "raw": clause,
                "업종_raw": None,
                "근거조항": chunk.get("clause_label"),
                "_source_chunk_id": chunk.get("chunk_id"),
                "_source_blocks": list(chunk.get("source_blocks") or []),
                "_salvaged_codes": sorted(missing),
            })
            covered |= missing
    return salvaged
