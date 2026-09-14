from datetime import date
import pytest
from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirement, derive_overall_status
from apps.api.app.qualification.rules.source_contracts import transport_contract, valid_contract
from apps.api.app.qualification.rules.askability import classify_askability

RAW = ('폐기물수집·운반업(1227) 등록업체. 단, 처분 또는 재활용업 허가 업체가 관계 법령상 해당 폐기물을 직접 수집·운반할 수 있는 '
       '장비·허가 조건을 갖춘 경우 수집·운반업 등록을 별도로 요구하지 않을 수 있다.')


def transport():
    return QualificationRequirement(requirement_key='transport', notice_version_id='v2', type='INDUSTRY', operator='MATCH',
        value='1227', raw=RAW, condition_complexity='composite', evidence_keys=['ev'], scope={'source_contract': transport_contract(RAW)})


def judge(req, codes):
    return judge_requirement(req, CompanyProfileSnapshot(company_id='company', industries=[ProfileIndustryFact(code=c, name=c) for c in codes]),
                             preflight_case_id='case', reference_date=date(2026, 9, 15))


def test_code_in_name_matches_and_conflicting_source_does_not():
    req = transport().model_copy(update={'value': '폐기물수집·운반업(1227)', 'raw': '폐기물수집·운반업(1227) 등록업체', 'scope': {}, 'condition_complexity': 'simple'})
    assert judge(req, ['1227']).status == 'SATISFIED'
    assert judge(req.model_copy(update={'raw': '폐기물수집·운반업(1224) 등록업체'}), ['1227']).status == 'UNKNOWN'


def test_registered_or_unknown_exception_not_automatic_negative():
    req = transport()
    assert judge(req, ['1227']).status == 'SATISFIED'
    assert judge(req, ['1224']).status == 'UNKNOWN'
    assert classify_askability(req).askable


@pytest.mark.parametrize('change', [{'raw': RAW + ' 단, 추가 법적 제한을 적용한다.'}, {'evidence_keys': []}, {'value': '1224'}])
def test_changed_or_ungrounded_contract_cannot_bypass_composite_guard(change):
    req = transport().model_copy(update=change)
    assert valid_contract(req) is None
    assert judge(req, ['1227']).status == 'UNKNOWN'


@pytest.mark.parametrize('statuses', [('SATISFIED', 'UNSATISFIED'), ('UNSATISFIED', 'SATISFIED'),
                                     ('SATISFIED', 'SATISFIED'), ('UNSATISFIED', 'UNSATISFIED')])
def test_unresolved_relation_never_silently_aggregates_as_and_or(statuses):
    requirements = [transport().model_copy(update={'requirement_key': key,
        'scope': {'source_group': {'key': 'waste', 'relation': 'UNRESOLVED'}}}) for key in ('disposal', 'transport')]
    judgments = [judge(r, ['1227']).model_copy(update={'status': status}) for r, status in zip(requirements, statuses)]
    assert derive_overall_status(requirements, judgments) == 'insufficient_data'
    # An independently unmet requirement still proves ineligibility.
    independent = transport().model_copy(update={'requirement_key': 'independent'})
    failure = judge(independent, []).model_copy(update={'status': 'UNSATISFIED'})
    assert derive_overall_status([*requirements, independent], [*judgments, failure]) == 'ineligible'
