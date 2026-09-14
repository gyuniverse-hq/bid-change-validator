"""실제 기존 판정기/계약/확장/정규화 모듈과 조건 그래프를 함께 실행한다.

모델 통신만 대역이다. 실제 DB와 HTTP 라우터를 띄운 E2E 테스트는 아니다.
"""
from __future__ import annotations

import copy
import importlib
import json
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from test_review_semantics import (ROOT, PREFIX, Model, atom, compiled_complex, decision, group,
                                   leaf, not_requirement, qualifier, run, source, sem)

bridge = importlib.import_module(PREFIX + '.review_semantic_judgment')
rules = importlib.import_module(ROOT + '.qualification.rules.judgment')
contracts = importlib.import_module(ROOT + '.ai.contracts')

DAY = date(2026, 7, 1)


def profile(*, industries=(), certifications=(), performances=(), **changes):
    data = dict(company_id='company-1', region_name='서울특별시', company_size='SMALL',
        industries=[{'code': code, 'name': code, 'verified': True} for code in industries],
        certifications=[{'ref': f'cert-{n}', 'name': name, 'verified': True} for n, name in enumerate(certifications)],
        staff={'total_count': 7}, performances=list(performances),
        completeness={'performances': True, 'certifications': True, 'industries': True})
    data.update(changes)
    return rules.CompanyProfileSnapshot.model_validate(data)


def record(ref, amount=100_000_000, completed='2026-06-01', fields=None):
    return {'ref': ref, 'name': '단체급식 실적', 'amount': amount,
            'completed_at': completed, 'fields': ['단체급식'] if fields is None else fields, 'verified': True}


def judge(d, p=None, **kwargs):
    return bridge.judge_semantic_decision(d, profile() if p is None else p,
        preflight_case_id='case-1', reference_date=kwargs.pop('reference_date', DAY), **kwargs)


def compile_one(text, type_, value, **changes):
    result, _ = run(text, lambda k: decision(k, [atom(k, text=text, value=value, type_=type_, **changes)]))
    assert result.coverage.coverage_status == 'COMPLETE', result.audit()
    assert not result.decisions[0].pending_codes, result.decisions[0].audit()
    return result.decisions[0]


def count_decision():
    text = '입찰공고일 기준 최근 2년 이내 1일 평균 800식 이상을 1년 이상 운영한 사업장 2개 이상 실적'
    def make(k):
        return decision(k, [atom(k, text=text, value='2개 이상', type_='PERFORMANCE_COUNT', qualifiers=[
            qualifier(k, 'LOOKBACK_WINDOW', '최근 2년 이내', 'NOTICE_DATE', '입찰공고일 기준'),
            qualifier(k, 'OPERATION_DURATION', '1년 이상'), qualifier(k, 'DAILY_VOLUME', '1일 평균 800식 이상')])])
    result, _ = run(text, make)
    assert not result.decisions[0].pending_codes
    return result.decisions[0]


def amount_decision(*, aggregation='MAX', tax=False, period=False):
    number = '2억원(부가세 포함) 이상' if tax else '2억원 이상'
    aggr = {'MAX': '단일', 'SUM': '합산', 'UNSPECIFIED': ''}[aggregation]
    text = f'{"입찰공고일 기준 최근 3년 이내 " if period else ""}{number} {aggr} 실적 보유'
    def make(k):
        return decision(k, [atom(k, text=text, value=number, type_='PERFORMANCE_AMOUNT', aggregation=aggregation,
            aggregation_source=source(k, aggr) if aggr else None,
            qualifiers=[qualifier(k,'LOOKBACK_WINDOW','최근 3년 이내','NOTICE_DATE','입찰공고일 기준')] if period else [])])
    result, _ = run(text, make)
    assert not result.decisions[0].pending_codes, result.decisions[0].audit()
    return result.decisions[0]


@pytest.mark.parametrize('industries,certs,expected', [
    (('1257',), (), 'UNSATISFIED'),
    (('1257',), ('ISO 9001',), 'SATISFIED'),
    (('1227',), (), 'SATISFIED'),
    ((), ('ISO 9001',), 'UNSATISFIED'),
    ((), (), 'UNSATISFIED'),
    (('1257',), ('ISO 27001',), 'UNSATISFIED'),
])
def test_nested_graph_uses_real_company_judgments(industries, certs, expected):
    answer = judge(compiled_complex(), profile(industries=industries, certifications=certs))
    assert answer.status == expected
    assert len(answer.atoms) == 3
    assert answer.rule_version == rules.RULE_VERSION
    assert all(item.reason_code in {'RULE_MATCH','RULE_MISMATCH'} for item in answer.atoms)


@pytest.mark.parametrize('industries,expected', [(('1257',), 'UNKNOWN'), (('1227',), 'SATISFIED')])
def test_missing_certification_fact_is_unknown_but_other_or_branch_can_prove_pass(industries, expected):
    p = profile(industries=industries, completeness={'industries': True, 'certifications': False})
    answer = judge(compiled_complex(), p)
    assert answer.status == expected
    assert next(a for a in answer.atoms if a.atom_id == 'cert').status == 'UNKNOWN'


def test_nested_atoms_keep_real_source_quotes_and_original_guard_still_runs():
    d = compiled_complex()
    for item in d.atoms:
        data = json.loads(item.requirement_json)
        req = contracts.QualificationRequirement.model_validate(data)
        assert req.raw in '가공업(1257)을 등록하고 ISO 9001 인증을 보유한 업체 또는 운반업(1227)을 등록한 업체'
        assert all(ref in {s.evidence_id for s in d.sources} for ref in req.evidence_keys)
    assert rules.judge_requirement.__module__.endswith('qualification.rules.judgment')


def test_same_record_filters_do_not_pool_different_records():
    p = profile(performances=[record('x'), record('y')])
    facts = [bridge.RecordObservation('x','EX',6,900), bridge.RecordObservation('y','EY',18,700)]
    answer = judge(count_decision(), p, anchor_dates={'NOTICE_DATE':DAY}, record_observations=facts)
    assert answer.status == 'UNSATISFIED'
    assert answer.atoms[0].reason_code == 'SAME_RECORD_FILTERS'
    assert json.loads(answer.atoms[0].profile_refs_json) == []


def test_two_qualified_records_satisfy_count():
    p = profile(performances=[record('x'), record('y')])
    facts = [bridge.RecordObservation('x','EX',12,800), bridge.RecordObservation('y','EY',18,900)]
    answer = judge(count_decision(), p, anchor_dates={'NOTICE_DATE':DAY}, record_observations=facts)
    assert answer.status == 'SATISFIED'
    assert {x['value'] for x in json.loads(answer.atoms[0].profile_refs_json)} == {'x','y'}


def test_missing_observation_is_not_zero():
    p = profile(performances=[record('x'),record('y')])
    assert judge(count_decision(),p,anchor_dates={'NOTICE_DATE':DAY}).status == 'UNKNOWN'


@pytest.mark.parametrize('complete,expected', [(True,'UNSATISFIED'),(False,'UNKNOWN')])
def test_not_enough_qualifying_records_distinguishes_collection_completeness(complete, expected):
    p=profile(performances=[record('x')],completeness={'performances':complete})
    assert judge(count_decision(),p,anchor_dates={'NOTICE_DATE':DAY},
        record_observations=[bridge.RecordObservation('x','EX',12,800)]).status == expected


def test_enough_confirmed_records_can_pass_even_when_collection_is_incomplete():
    p=profile(performances=[record('x'),record('y')],completeness={'performances':False})
    assert judge(count_decision(),p,anchor_dates={'NOTICE_DATE':DAY}, record_observations=[
        bridge.RecordObservation('x','EX',12,800),bridge.RecordObservation('y','EY',12,800)]).status=='SATISFIED'


def test_record_outside_lookback_is_not_counted_despite_good_measurements():
    p=profile(performances=[record('x'),record('y',completed='2020-06-01')])
    assert judge(count_decision(),p,anchor_dates={'NOTICE_DATE':DAY},record_observations=[
        bridge.RecordObservation('x','EX',12,800),bridge.RecordObservation('y','EY',12,800)]).status=='UNSATISFIED'


def test_lookback_anchor_requires_backend_date_not_clock_default():
    answer=judge(count_decision(),profile(performances=[record('x')]))
    assert answer.status=='UNKNOWN'
    assert answer.atoms[0].reason_code=='MISSING_REFERENCE_DATE'


@pytest.mark.parametrize('aggregation,expected',[('MAX','UNSATISFIED'),('SUM','SATISFIED'),('UNSPECIFIED','UNKNOWN')])
def test_real_amount_rules_respect_single_sum_and_ambiguous_aggregation(aggregation,expected):
    p=profile(performances=[record('x',120_000_000),record('y',120_000_000)])
    answer=judge(amount_decision(aggregation=aggregation),p)
    assert answer.status==expected


def test_large_single_record_satisfies_amount():
    assert judge(amount_decision(),profile(performances=[record('x',250_000_000)])).status=='SATISFIED'


@pytest.mark.parametrize('facts,expected',[((), 'UNKNOWN'),
    ((bridge.RecordObservation('x','EX',amount_tax_basis='EXCLUDED'),),'UNKNOWN'),
    ((bridge.RecordObservation('x','EX',amount_tax_basis='INCLUDED'),),'SATISFIED')])
def test_tax_basis_must_be_confirmed_before_amount_comparison(facts,expected):
    p=profile(performances=[record('x',250_000_000)])
    answer=judge(amount_decision(tax=True),p,record_observations=facts)
    assert answer.status==expected


def test_amount_lookback_uses_explicit_notice_date():
    p=profile(performances=[record('x',250_000_000,completed='2022-01-01')])
    answer=judge(amount_decision(period=True),p,anchor_dates={'NOTICE_DATE':DAY})
    assert answer.status=='UNSATISFIED'


@pytest.mark.parametrize('text,type_,value,changes,expected',[
    ('서울특별시에 소재한 업체','REGION','서울특별시',{},'SATISFIED'),
    ('부산광역시에 소재한 업체','REGION','부산광역시',{},'UNSATISFIED'),
    ('소기업인 업체','COMPANY_SIZE','소기업',{},'SATISFIED'),
    ('대기업인 업체','COMPANY_SIZE','대기업',{},'UNSATISFIED'),
    ('인력 5명 이상 보유 업체','STAFF','5명 이상',{},'SATISFIED'),
    ('인력 10명 이상 보유 업체','STAFF','10명 이상',{},'UNSATISFIED'),
])
def test_other_supported_types_use_existing_judge(text,type_,value,changes,expected):
    answer=judge(compile_one(text,type_,value,**changes))
    assert answer.status==expected


def test_pending_scope_does_not_turn_partial_atoms_into_false_final_decision():
    d=replace(compiled_complex(),pending_codes=('CONTEXT_APPLICABILITY_PENDING',))
    answer=judge(d)
    assert answer.status=='UNKNOWN'
    assert answer.atoms==()
    assert answer.pending_codes==d.pending_codes


def test_modified_compiled_value_cannot_disagree_with_graph():
    d=compiled_complex(); first=d.atoms[0]; raw=json.loads(first.requirement_json); raw['value']='9999'
    bad=replace(d,atoms=(replace(first,requirement_json=json.dumps(raw)),*d.atoms[1:]))
    with pytest.raises(ValueError,match='canonical payload and graph differ'):
        judge(bad)


def test_incomplete_atom_catalog_is_rejected():
    d=compiled_complex()
    with pytest.raises(ValueError,match='compiled atoms'):
        judge(replace(d,atoms=d.atoms[:-1]))


@pytest.mark.parametrize('value',[None,datetime(2026,7,1),'2026-07-01'])
def test_explicit_date_type_required(value):
    with pytest.raises(ValueError):judge(compiled_complex(),reference_date=value)


def test_duplicate_performance_ids_are_rejected():
    with pytest.raises(ValueError,match='duplicate record'):
        judge(count_decision(),profile(performances=[record('same'),record('same')]))


@pytest.mark.parametrize('facts',[
    [bridge.RecordObservation('x','a'),bridge.RecordObservation('x','b')],
    [bridge.RecordObservation('foreign','a')],
    [{'record_ref':'x','daily_meals':900}],
])
def test_observation_identity_and_typed_facts_required(facts):
    with pytest.raises(ValueError):
        judge(count_decision(),profile(performances=[record('x')]),record_observations=facts)


@pytest.mark.parametrize('change',[{'operation_months':-1},{'daily_meals':True},{'amount_tax_basis':'GUESS'}, {'basis_id':''}])
def test_bad_observation_does_not_enter_judge(change):
    with pytest.raises(ValueError):bridge.RecordObservation(**{'record_ref':'x','basis_id':'basis',**change})


def test_profile_or_date_changes_context_fingerprint_not_requirement_content():
    d=compiled_complex()
    first=judge(d,profile(industries=['1257']))
    second=judge(d,profile(industries=['1227']))
    third=judge(d,profile(industries=['1257']),reference_date=date(2026,7,2))
    assert len({a.context_sha256 for a in (first,second,third)})==3
    assert len({a.semantic_sha256 for a in (first,second,third)})==1


def test_non_mandatory_role_is_retained_and_not_promoted_to_notice_failure():
    text='업종코드 1450 등록 업체'
    result,_=run(text,lambda k:decision(k,role='preferred'))
    answer=judge(result.decisions[0])
    assert answer.role=='preferred'
    assert answer.status=='UNSATISFIED'  # 이 선호 조건의 결과일 뿐 전체 자격미달이 아니다.


def test_full_internal_path_compiles_and_judges_without_db_or_profile_leak_to_model():
    text,_=__import__('test_review_semantics').complex_case('dummy')
    from test_review_semantics import complex_case
    input_=SimpleNamespace(notice_id='notice-1',notice_version_id='V1',documents=[SimpleNamespace(
        document_id='D1',file_sha256='a'*64,extracted_text_sha256='b'*64,
        extracted_blocks=[{'block_index':0,'text':text,'page':4}])])
    model=Model(lambda payload,n:{'decisions':[complex_case(k)[1] for k in payload['target_candidate_ids']]})
    p=profile(industries=['1257'],company_id='PRIVATE_COMPANY_DO_NOT_SEND')
    answer=bridge.analyze_qualification_semantics(input_,structured_extract=model,profile=p,
        preflight_case_id='case-1',reference_date=DAY)
    assert len(model.calls)==1
    assert answer.judgments[0].status=='UNSATISFIED'
    assert 'PRIVATE_COMPANY_DO_NOT_SEND' not in json.dumps(model.calls)
    audit=answer.audit()
    assert audit['notice_overall_status'] is None
    assert audit['judgments'][0]['atom_count']==3
    assert text not in json.dumps(audit,ensure_ascii=False)
    assert 'ISO 9001' not in json.dumps(audit,ensure_ascii=False)


def test_internal_path_keeps_unresolved_candidate_and_missing_state():
    input_=SimpleNamespace(notice_id='N',notice_version_id='V',documents=[SimpleNamespace(
        document_id='D',file_sha256=None,extracted_text_sha256=None,
        extracted_blocks=[{'block_index':0,'text':'업종코드 1450 등록 업체'}])])
    model=Model(lambda payload,n:{'decisions':[]})
    result=bridge.analyze_qualification_semantics(input_,structured_extract=model,profile=profile(),
        preflight_case_id='C',reference_date=DAY)
    assert result.judgments==()
    assert result.execution.coverage.coverage_status=='INCOMPLETE'
    assert len(model.calls)==2
    assert result.audit()['notice_overall_status'] is None


def test_judging_does_not_mutate_profile_or_semantics():
    d=compiled_complex();p=profile(industries=['1227']);prior=p.model_dump(mode='json');source=copy.deepcopy(d)
    judge(d,p)
    assert p.model_dump(mode='json')==prior
    assert d==source


@pytest.mark.parametrize('change',[{'profile':None},{'preflight_case_id':''},
    {'anchor_dates':{'INVENTED':DAY}}, {'anchor_dates':{'NOTICE_DATE':'2026-07-01'}},
    {'record_observations':[bridge.RecordObservation('foreign','B')]}, {'reference_date':None}])
def test_invalid_company_context_fails_before_paid_model_call(change):
    model=Model(lambda payload,n:pytest.fail('must not call model'))
    input_=SimpleNamespace(notice_id='N',notice_version_id='V',documents=[])
    args=dict(profile=profile(),preflight_case_id='C',reference_date=DAY)
    args.update(change)
    with pytest.raises(ValueError):
        bridge.analyze_qualification_semantics(input_,structured_extract=model,**args)
    assert model.calls==[]


def test_case_identity_is_part_of_judgment_context():
    d=compiled_complex();p=profile()
    first=judge(d,p)
    second=bridge.judge_semantic_decision(d,p,preflight_case_id='other-case',reference_date=DAY)
    assert first.context_sha256!=second.context_sha256
