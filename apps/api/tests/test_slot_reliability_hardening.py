"""7-D1~4 회귀. 원문과 모델 응답은 합성이고 판정 함수는 실제 구현이다."""
import itertools
import json
from datetime import date
from types import SimpleNamespace
import pytest
from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.ai.qualification.canonical.slot_money import normalize_slot_money, money_normalization_error
from apps.api.app.ai.qualification.canonical.legacy_slots import adapt_legacy_slot
from apps.api.app.ai.qualification.canonical.canonicalize import canonicalize_validated_slots
from apps.api.app.ai.qualification.canonical.deduplicate import deduplicate_requirements, predicate_identity
from apps.api.app.ai.qualification.canonical.industry_binding import registration_alias_code
from apps.api.app.ai.qualification.extraction.analysis_pipeline import QualificationAnalysisInput, analyze_qualification_documents, _normalize_extracted_slots
from apps.api.app.ai.qualification.extraction.requirement_extraction import validate_extracted_slot, extract_legacy_slots, select_eligibility_chunks
from apps.api.app.ai.qualification.extraction.analysis_result import DroppedRequirement
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot, judge_requirements, derive_overall_status

DAY = date(2026, 9, 15)
LONG = '단체급식업 등록업체로서 영업신고(업종코드 : 1450)를 한 업체'
SHORT = '단체급식업 등록업체'


def request(raw):
    return QualificationAnalysisInput(notice_id='n', notice_version_id='v', documents=[{
        'document_id': 'd', 'extracted_blocks': [{'block_index': 0, 'text': raw}]}])


class Model:
    def __init__(self, slots): self.slots = slots
    def __call__(self, prompt, body, schema):
        if schema['name'] == 'eligibility_slots':
            return {'requirements': self.slots}
        data = json.loads(body)
        return {'decisions': [{'candidate_id': key, 'status': 'REQUIREMENT', 'reason': None, 'slots': [
            {'type': s['유형'], 'basis': 'SELF_CONTAINED', 'fields': [{'name': f, 'quote': v, 'source_candidate_id': key}
                for f, v in s.items() if f.endswith('_raw') and v]} for s in self.slots]}
            for key in data['target_candidate_ids']]}


@pytest.mark.parametrize('raw,value', [('4억원 이상', 400000000), ('금 5천만원 이상', 50000000),
    ('1.3억원 이상', 130000000), ('50,000,000원 이상', 50000000), ('1억원 (부가세 포함) 이상', 100000000),
    ('오천만원 이상', 50000000), ('1원 이상', 1), ('0.0333원 이상', 0.0333), ('1억 5천만원 이상', 150000000),
    ('0만원 이상', 0), ('영만원 이상', 0)])
def test_explicit_money_no_arbitrary_floor(raw, value):
    out = normalize_slot_money(raw)
    assert (out['parse_status'], out['value'], out['unit'], out['op']) == ('success', value, 'KRW', '>=')


@pytest.mark.parametrize('raw', ['1일 평균 800식 이상', '2명 이상', '최근 3년', '5% 이상', '1/1000 이상',
    '1억원 이상; 2억원 이상', '1억원 이상 및 5명 이상', '5,00원 이상', '1 2원 이상', '예산 5억원 이상',
    '1억원 이상 (예외: 2명)', '2억원 이상 1억원 이하', '1억원 초과 1억원 이하', '십십원 이상', '만억원 이상'])
def test_non_money_or_invalid_number_rejected(raw):
    assert normalize_slot_money(raw)['parse_status'] == 'failed'


@pytest.mark.parametrize('raw', ['1억원 이상 2억원 이하', '1억원 이상 ~ 2억원 미만'])
def test_range_preserves_limits(raw):
    out = normalize_slot_money(raw)
    assert out['parse_status'] == 'success' and out['range']['min'] == 100000000 and out['range']['max'] == 200000000


@pytest.mark.parametrize('unit', [None, 'MONTH', 'PERSON', 'COUNT', 'PERCENT'])
def test_direct_canonical_wrong_unit_rejected(unit):
    rows, diag = adapt_legacy_slot({'유형': '실적요건', 'raw': '급식 실적 1일 평균 800식 이상',
        '금액_norm': {'parse_status': 'success', 'value': 0.0333, 'unit': unit, 'op': '>='}}, notice_version_id='v', key_prefix='r')
    assert not rows and diag[0]['reason'] == 'MONEY_UNIT_MISMATCH'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True, '50'])
def test_invalid_numeric_value_rejected(value):
    assert money_normalization_error({'parse_status': 'success', 'unit': 'KRW', 'value': value, 'op': '>='})


@pytest.mark.parametrize('strategy', ['legacy', 'review_v1'])
def test_day_quantity_cannot_become_performance_money(strategy):
    raw = '합산 급식 운영 실적은 1일 평균 800식 이상이어야 한다.'
    result = analyze_qualification_documents(request(raw), structured_extract=Model([
        {'유형': '실적요건', 'raw': raw, '금액_raw': '1일 평균 800식 이상'}]), extraction_strategy=strategy)
    assert result.status == 'PARTIAL' and not result.requirements
    assert any(d.code == 'UNMAPPED_PERFORMANCE' for d in result.diagnostics)
    company = CompanyProfileSnapshot.model_validate({'company_id': 'c', 'performances': [{
        'ref': 'p', 'name': '급식', 'status': 'COMPLETED', 'amount': 1, 'end_date': '2026-09-01'}],
        'completeness': {'performances': True}})
    judged = judge_requirements(result.requirements, company, preflight_case_id='x', reference_date=DAY, analysis_status=result.status)
    assert judged.overall_status == 'insufficient_data'


@pytest.mark.parametrize('bad', [{'value': 0.03, 'unit': 'MONTH'}, {'value': 1, 'unit': 'KRW'}])
def test_custom_normalizer_must_match_source(bad):
    out = _normalize_extracted_slots([{'금액_raw': '1억원 이상'}], normalize_value=lambda _: {'parse_status': 'success', 'op': '>=', **bad})
    assert out[0]['금액_norm']['parse_status'] == 'failed'


def req(key, group='g', operator='ALL_OF', value='1450', **kw):
    return QualificationRequirement(requirement_key=key, notice_version_id='v', type='INDUSTRY', operator='MATCH', value=value,
        raw=kw.pop('raw', LONG), requirement_group_key=group, group_operator=operator, evidence_keys=[key+'-e'], **kw)


def test_duplicate_combines_only_related_evidence_and_preserves_inputs():
    rows = [req('a'), req('b')]
    before = [r.model_dump() for r in rows]
    kept, diag = deduplicate_requirements(rows)
    assert len(kept) == 1 and set(kept[0].evidence_keys) == {'a-e', 'b-e'}
    assert set(diag[0]['evidence_keys']) == {'a-e', 'b-e'}
    assert [r.model_dump() for r in rows] == before


@pytest.mark.parametrize('change', [{'unit': 'MONTH'}, {'period_months': 36}, {'operator': '='}, {'scope': {'region': '서울'}},
    {'requirement_role': 'preferred', 'required': False}, {'condition_complexity': 'composite'}, {'notice_version_id': 'other'}])
def test_semantic_difference_not_duplicate(change):
    a = req('a'); b = req('b').model_copy(update=change)
    assert predicate_identity(a) != predicate_identity(b) and len(deduplicate_requirements([a, b])[0]) == 2


@pytest.mark.parametrize('reverse', [True, False])
def test_preferred_cannot_swallow_mandatory(reverse):
    rows = [req('m'), req('p', requirement_role='preferred', required=False)]
    if reverse: rows.reverse()
    kept, _ = deduplicate_requirements(rows)
    company = CompanyProfileSnapshot.model_validate({'company_id': 'c', 'completeness': {'industries': True}})
    assert len(kept) == 2
    assert judge_requirements(kept, company, preflight_case_id='x', reference_date=DAY).overall_status == 'ineligible'


@pytest.mark.parametrize('values', itertools.product(['SATISFIED', 'UNSATISFIED', 'UNKNOWN'], repeat=3))
def test_distinct_or_groups_keep_every_edge(values):
    rows = [req('a1', 'g1', 'ANY_OF', '1450'), req('b', 'g1', 'ANY_OF', '1227'), req('a2', 'g2', 'ANY_OF', '1450'), req('c', 'g2', 'ANY_OF', '6770')]
    statuses = dict(zip(('1450', '1227', '6770'), values))
    judged = [SimpleNamespace(requirement_key=r.requirement_key, status=statuses[r.value]) for r in rows]
    kept, _ = deduplicate_requirements(rows)
    assert len(kept) == 4 and derive_overall_status(rows, judged) == derive_overall_status(kept, judged)


def test_singleton_all_duplicate_may_combine_but_unmodeled_raw_must_not():
    assert len(deduplicate_requirements([req('a', 'a'), req('b', 'b')])[0]) == 1
    assert len(deduplicate_requirements([req('a', raw='급식 사업장 2개'), req('b', raw='급식 사업장 5개')])[0]) == 2


@pytest.mark.parametrize('name', ['ISO 9001', '직접생산확인증명서', '건설업등록', 'KS Q 27001'])
def test_other_certification_not_alias(name):
    assert registration_alias_code(name, LONG) is None
    assert registration_alias_code(name, f'{name} 및 폐기물수집운반업(1227) 등록업체') is None


@pytest.mark.parametrize('name', ['단체급식업등록', '단체급식업', '영업신고'])
def test_explicit_single_name_and_code_alias(name):
    assert registration_alias_code(name, LONG) == '1450'


@pytest.mark.parametrize('reverse', [False, True])
def test_double_classification_fixed_with_real_judge(reverse):
    blocks = [{'document_id': 'd', 'block_index': 0, 'text': LONG}]
    slots = [{'유형': '등록요건', 'raw': SHORT, '등록인증_raw': '단체급식업등록', '_source_blocks': blocks},
        {'유형': '업종요건', 'raw': LONG, '업종_raw': '단체급식업', '_source_blocks': blocks}]
    out = canonicalize_validated_slots(list(reversed(slots)) if reverse else slots, notice_version_id='v')
    assert [(r.type, r.value) for r in out['requirements']] == [('INDUSTRY', '1450')]
    assert len(out['requirements'][0].evidence_keys) == 2
    company = CompanyProfileSnapshot.model_validate({'company_id': 'c', 'industries': [{'code': '1450', 'name': '단체급식업'}],
        'completeness': {'industries': True, 'certifications': True}})
    assert judge_requirements(out['requirements'], company, preflight_case_id='x', reference_date=DAY).overall_status == 'eligible'


def test_real_certificate_not_swallowed_by_incidental_code():
    rows, _ = adapt_legacy_slot({'유형': '등록요건', 'raw': '업종코드: 1468 업체는 ISO 27001 인증 보유', '등록인증_raw': 'ISO 27001'}, notice_version_id='v', key_prefix='r')
    assert rows[0].type == 'REGISTRATION_CERTIFICATION' and rows[0].value == 'ISO 27001'


@pytest.mark.parametrize('raw', ['건설업 등록 및 영업신고(업종코드 : 1450)',
    '단체급식업 등록 및 건설업 등록, 영업신고(업종코드 : 1450)', '단체급식업(1450) 및 다른업(1227)'])
def test_multiple_names_codes_not_aliased(raw):
    assert registration_alias_code('단체급식업등록', raw) is None


@pytest.mark.parametrize('raw,name', [('나라장터 입찰참가자격등록을 마친 업체', '입찰참가자격등록'),
    ('G2B 이용자 등록 완료 업체', 'G2B 이용자등록'), ('나라장터에 등록한 업체', '나라장터'),
    ('「국가종합전자조달시스템 입찰참가자격등록규정」에 따른 업체', '국가종합전자조달시스템 입찰참가자격등록규정')])
def test_pure_procedure_retained_unchecked(raw, name):
    out = canonicalize_validated_slots([{'유형': '등록요건', 'raw': raw, '등록인증_raw': name,
        '_source_blocks': [{'document_id': 'd', 'block_index': 0, 'text': raw}]}], notice_version_id='v')
    assert not out['requirements'] and out['evidence'][0].quote == raw
    d = next(d for d in out['diagnostics'] if d['code'] == 'PROCEDURAL_REQUIREMENT_REVIEW')
    assert d['verification_status'] == 'NOT_CHECKED' and d['evidence_keys']


@pytest.mark.parametrize('strategy', ['legacy', 'review_v1'])
def test_mixed_procedure_preserves_industry_and_unchecked_state(strategy):
    raw = '나라장터 입찰참가자격등록을 마치고 업종코드 1227을 등록한 업체'
    result = analyze_qualification_documents(request(raw), structured_extract=Model([
        {'유형': '업종요건', 'raw': raw, '업종_raw': '1227'}]), extraction_strategy=strategy)
    assert [(r.type, r.value) for r in result.requirements] == [('INDUSTRY', '1227')]
    assert result.status == 'PARTIAL'
    assert any(d.code == 'PROCEDURAL_REQUIREMENT_REVIEW' and d.severity == 'WARNING' for d in result.diagnostics)
    company = CompanyProfileSnapshot.model_validate({'company_id': 'c', 'industries': [{'code': '1227', 'name': '운반업'}]})
    judged = judge_requirements(result.requirements, company, preflight_case_id='x', reference_date=DAY, analysis_status=result.status)
    assert judged.judgments[0].status == 'SATISFIED' and judged.overall_status == 'insufficient_data'


def test_source_normalization_returns_real_quote():
    text = '실적 조건은 각 단체급식소※(1일 평균 800식 이상)를 운영한 업체'
    slot = {'raw': text.replace('※', ''), '경험분야_raw': '각 단체급식소(1일평균800식이상)'}
    assert validate_extracted_slot(slot, [{'text': text}])[0]
    assert slot['raw'] == text and slot['경험분야_raw'] == '각 단체급식소※(1일 평균 800식 이상)'
    bounds = slot['_grounding_basis']['fields']['경험분야_raw']
    assert text[bounds['start']:bounds['end']] == slot['경험분야_raw']


@pytest.mark.parametrize('source,quote', [('12년 이상', '2년 이상'), ('1.3억원 이상', '3억원 이상'), ('14501 등록', '1450')])
def test_numeric_substring_rejected(source, quote):
    assert not validate_extracted_slot({'raw': quote}, [{'text': source}])[0]


def test_unrelated_budget_fragments_and_ambiguous_source_rejected():
    slot = {'raw': '실적 1억원 이상 보유', '금액_raw': '5억원'}
    assert not validate_extracted_slot(slot, [{'text': slot['raw'] + '\n사업예산 5억원'}])[0]
    assert slot['_rejected_detail']['field'] == '금액_raw'
    assert not validate_extracted_slot({'raw': '최근 2년 내 1년 이상 운영', '기간_raw': '최근 2년; 1년 이상'}, [{'text': '최근 2년 내 1년 이상 운영'}])[0]
    assert not validate_extracted_slot({'raw': '등록 업체'}, [{'text': '등록 업체'}, {'text': '등록 업체'}])[0]


def test_drop_diagnostic_roundtrip_keeps_old_json_shape():
    old = DroppedRequirement(raw='x', reason_code='RAW_NOT_FOUND_IN_SOURCE')
    assert old.model_dump() == {'raw': 'x', 'reason_code': 'RAW_NOT_FOUND_IN_SOURCE'}
    result = extract_legacy_slots([{'text': '실적 1억원 이상 보유', 'chunk_id': 'c'}], structured_extract=lambda *a: {
        'requirements': [{'유형': '실적요건', 'raw': '실적 1억원 이상 보유', '금액_raw': '5억원'}]}, max_retry=0)
    drop = result['dropped_requirements'][0]
    assert DroppedRequirement.model_validate(drop).model_dump() == drop
    assert drop['detail_field'] == '금액_raw' and drop['detail_value'] == '5억원'


def test_heading_children_date_and_document_boundary():
    def c(label, text, doc='d'):
        return {'clause_label': label, 'text': text, 'source_blocks': [{'document_id': doc}]}
    chunks = [c('3', '3. 참가자격'), c('가', '가. 업종조건'), c('1', '1)세부조건'), c('2026.09.15', '2026.09.15. 등록기한'), c('나', '나. 지역조건'), c('4', '4. 입찰 방법')]
    assert select_eligibility_chunks(chunks) == chunks[:-1]
    assert select_eligibility_chunks(chunks[:2] + [c(None, '다른 문서', 'other')]) == chunks[:2]
