"""모델이 업종코드 조항을 빠뜨려도 요건이 판정기에 닿는지.

[재현 2026-09-15] 같은 공고를 3회 돌리면 모델이 어떤 실행에서는 업종 조항을 아예 안 올린다.
구내식당은 "영업신고(업종코드 : 1450)" 슬롯이, 남원글로컬은 "(1257) 또는 (6770) 또는
(6786)" 조항이 통째로 빠졌다. 원문의 숫자는 그대로인데. 모델이 빠뜨린 것을 코드가 채운다.
"""

from __future__ import annotations

from apps.api.app.ai.qualification.extraction.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from apps.api.app.ai.qualification.extraction.code_salvage import (
    industry_codes_in,
    salvage_missing_industry_slots,
)


CAFETERIA = (
    "3. 입찰 참가 자격\n"
    "가. 국가를 당사자로 하는 계약에 관한 법률 시행령 제12조에 의한 자격을 갖춘 업체\n"
    "나. 식품위생법에 의거 단체급식업 등록업체로서 식당허가 등에 결격사유가 없는 업체 "
    "식품위생법에 따른 인·허가를 득하고 동법 시행령에 따라 영업신고(업종코드 : 1450)를 하여 "
    "집단급식소 영업이 가능한 법인사업자\n"
    "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체"
)

WASTE = (
    "3. 입찰 참가 자격\n"
    "○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
    "1) 「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 또는 폐기물중간재활용업(6770) 또는 폐기물종합재활용업(6786) 등록업체\n"
    "2) 폐기물수집·운반업(1227) 등록업체"
)


def _input(text: str) -> QualificationAnalysisInput:
    return QualificationAnalysisInput(
        notice_id="notice-1",
        notice_version_id="version-1",
        documents=[QualificationDocumentInput(
            document_id="doc-1",
            extracted_blocks=[{"block_index": 0, "page": 1, "location": "p.1", "text": text}],
        )],
    )


def test_codes_are_read_only_in_industry_context() -> None:
    assert industry_codes_in("영업신고(업종코드 : 1450)를 한 업체") == {"1450"}
    assert industry_codes_in("폐기물수집·운반업(1227) 등록업체") == {"1227"}
    assert industry_codes_in("2024년 6월 30일까지 (2026) 1500제곱미터") == set()


def test_the_omitted_cafeteria_code_is_filled_from_source() -> None:
    """구내식당 run2 그대로 — 모델이 '나.' 조항의 1450 슬롯을 안 냈다."""
    def model_omits_industry(system, body, schema):
        return {"requirements": [{
            "유형": "실적요건",
            "raw": "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체",
            "경험분야_raw": "각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영",
            "근거조항": "다",
        }]}

    result = analyze_qualification_documents(_input(CAFETERIA), structured_extract=model_omits_industry)

    industries = [item for item in result.requirements if item.type == "INDUSTRY"]
    assert [item.value for item in industries] == ["1450"]
    assert "영업신고(업종코드 : 1450)" in industries[0].raw
    # 빠뜨렸다는 사실은 남고, 분석 상태를 PARTIAL 로 끌어내리지는 않는다.
    assert any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)
    assert result.status == "SUCCEEDED"


def test_the_omitted_alternation_clause_becomes_an_any_of_group() -> None:
    """남원글로컬 run0 그대로 — 업종 조항이 통째로 없다. '또는' 관계까지 살아야 한다."""
    def model_omits_everything_industrial(system, body, schema):
        return {"requirements": []}

    result = analyze_qualification_documents(_input(WASTE), structured_extract=model_omits_everything_industrial)

    by_value = {item.value: item for item in result.requirements if item.type == "INDUSTRY"}
    assert set(by_value) == {"1257", "6770", "6786", "1227"}
    assert {by_value[c].group_operator for c in ("1257", "6770", "6786")} == {"ANY_OF"}
    assert by_value["1227"].group_operator == "ALL_OF"


def test_nothing_is_added_when_the_model_already_covered_the_code() -> None:
    """모델이 냈으면 코드는 가만히 있는다. 두 번 만들면 중복이고 개수가 부푼다."""
    def model_covers(system, body, schema):
        return {"requirements": [{
            "유형": "업종요건",
            "raw": "식품위생법에 따른 인·허가를 득하고 동법 시행령에 따라 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자",
            "업종_raw": "집단급식소",
            "근거조항": "나",
        }]}

    result = analyze_qualification_documents(_input(CAFETERIA), structured_extract=model_covers)

    assert [item.value for item in result.requirements if item.type == "INDUSTRY"] == ["1450"]
    assert not any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)


def test_a_duplicated_clause_across_documents_is_salvaged_once() -> None:
    chunks = [
        {"chunk_id": "A", "text": "나. 영업신고(업종코드 : 1450)를 한 업체", "source_blocks": [], "clause_label": "나"},
        {"chunk_id": "B", "text": "나. 영업신고(업종코드 : 1450)를 한 업체", "source_blocks": [], "clause_label": "나"},
    ]

    salvaged = salvage_missing_industry_slots(set(), chunks)

    assert len(salvaged) == 1
    assert salvaged[0]["_salvaged_codes"] == ["1450"]


def test_a_clause_the_model_emitted_but_mapping_could_not_use_is_still_filled() -> None:
    """[재현 2026-09-15 J14 run0] 모델이 "○ … 1) A(1257) 또는 B(6770) 또는 C(6786) 등록업체
    2) D(1227) 등록업체" 문단을 통째로 한 슬롯에 담았다. 마지막 조각에 코드가 둘이라 ANY_OF 로
    못 풀려 UNMAPPED. 모델이 냈다는 이유로 건너뛰면 네 코드가 영영 안 채워진다."""
    def model_emits_whole_paragraph(system, body, schema):
        return {"requirements": [{
            "유형": "등록요건",
            "raw": ("○ 입찰서 제출 마감일 전일까지 나라장터에 아래 업종 중 해당 자격을 등록한 업체이어야 한다.\n"
                    "1) 「폐기물관리법」 제25조에 따른 폐기물중간처분업(1257) 또는 폐기물중간재활용업(6770) 또는 폐기물종합재활용업(6786) 등록업체\n"
                    "2) 폐기물수집·운반업(1227) 등록업체"),
            "등록인증_raw": None,
            "근거조항": None,
        }]}

    result = analyze_qualification_documents(_input(WASTE), structured_extract=model_emits_whole_paragraph)

    by_value = {item.value: item for item in result.requirements if item.type == "INDUSTRY"}
    assert set(by_value) == {"1257", "6770", "6786", "1227"}
    # 모델 슬롯은 못 썼고 코드가 채웠다. 그 사실이 상태와 진단에 남는다.
    assert result.status == "PARTIAL"
    assert any(d.code == "INDUSTRY_CODE_SALVAGED_FROM_SOURCE" for d in result.diagnostics)
