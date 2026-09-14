"""상태와 기준 선택의 실제 구현을 검증한다. DB/LLM은 호출하지 않는다."""
import copy
import importlib
import json
import sys
import types
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'app/qualification'
PKG = '_qualification_state_pure_tests'
if PKG not in sys.modules:
    package = types.ModuleType(PKG)
    package.__path__ = [str(ROOT)]
    sys.modules[PKG] = package
m = importlib.import_module(PKG + '.state_contract')
s = importlib.import_module(PKG + '.semantic_state')
NOW = datetime(2026, 9, 15, 9, tzinfo=timezone.utc)
DAY = date(2026, 9, 15)
SCOPE = m.ReviewScope('CASE', 'NOTICE', 'V2', 'CO', 'rules-3')
PROFILE = m.payload_fingerprint({'company_id': 'CO', 'complete': True})


def analysis(**kwargs):
    return replace(m.AnalysisSnapshot('A2', 'V2', NOW, 'SUCCEEDED', ('R1', 'R2')), **kwargs)


def judgment(**kwargs):
    base = m.JudgmentSnapshot('J2', 'CASE', 'CO', 'V2', 'A2', NOW, 'rules-3',
        'SUCCEEDED', DAY, PROFILE, 'eligible', ('R1', 'R2'))
    return replace(base, **kwargs)


def resolve(aa=None, jj=None, **kwargs):
    return m.select_qualification_state(SCOPE, [analysis()] if aa is None else aa,
        [judgment()] if jj is None else jj, current_profile_sha256=kwargs.pop('profile', PROFILE),
        reference_date=kwargs.pop('day', DAY), **kwargs)


def test_available_saved_result_has_separate_unverified_completeness():
    out = resolve()
    assert out.selected_judgment_run_id == 'J2'
    assert out.freshness_state == 'CURRENT'
    assert out.coverage_state == 'UNVERIFIED'
    assert out.stored_overall_status == 'eligible'
    assert not out.full_notice_eligibility_asserted
    assert 'ANALYSIS_COMPLETENESS_UNVERIFIED' in out.reasons


@pytest.mark.parametrize('state', ['PENDING', 'RUNNING', 'FAILED'])
def test_latest_non_success_never_falls_back_to_previous_success(state):
    old = analysis(id='A1', created_at=NOW-timedelta(hours=1))
    result = resolve([old, analysis(status=state)], [judgment(analysis_run_id='A1')])
    assert result.analysis_run_id == 'A2'
    assert result.selected_judgment_run_id is None
    assert result.stored_overall_status is None
    assert result.display_state == ('ANALYSIS_FAILED' if state == 'FAILED' else 'ANALYSIS_RUNNING')


def test_unreviewed_judgment_required_and_read_failure_are_distinct():
    assert resolve([], []).display_state == 'UNREVIEWED'
    assert resolve(jj=[]).display_state == 'JUDGMENT_REQUIRED'
    assert m.lookup_failed(SCOPE).display_state == 'LOAD_FAILED'
    assert m.lookup_failed(SCOPE).execution_state == 'UNKNOWN'


def test_company_absent_is_not_an_empty_eligibility_result():
    result = m.select_qualification_state(replace(SCOPE, company_id=None), [], [], current_profile_sha256=None)
    assert result.display_state == 'PROFILE_REQUIRED'


@pytest.mark.parametrize('change, reason', [
    ({'analysis_run_id': 'A1'}, 'ANALYSIS_CHANGED'),
    ({'notice_version_id': 'V1'}, 'NOTICE_VERSION_CHANGED'),
    ({'rule_version': 'rules-2'}, 'RULE_VERSION_CHANGED'),
])
def test_old_analysis_version_or_rules_require_rejudgment(change, reason):
    result = resolve(jj=[judgment(**change)])
    assert result.display_state == 'REJUDGMENT_REQUIRED'
    assert reason in result.reasons
    assert result.stored_overall_status is None


@pytest.mark.parametrize('field', ['case_id', 'company_id'])
def test_foreign_judgment_never_leaks_status_or_id(field):
    result = resolve(jj=[judgment(**{field: 'PRIVATE_FOREIGN_ID'})])
    assert result.display_state == 'JUDGMENT_REQUIRED'
    assert 'PRIVATE_FOREIGN_ID' not in json.dumps(result.to_dict())


def test_foreign_analysis_is_ignored():
    assert resolve([analysis(notice_version_id='OTHER')], []).display_state == 'UNREVIEWED'


@pytest.mark.parametrize('profile, day, reason', [
    ('new-profile', DAY, 'PROFILE_CHANGED'),
    (PROFILE, date(2026,9,16), 'REFERENCE_DATE_CHANGED'),
])
def test_changed_profile_or_reference_is_stale_not_unreviewed(profile, day, reason):
    result = resolve(profile=profile, day=day)
    assert result.freshness_state == 'STALE'
    assert result.selected_judgment_run_id is None
    assert result.observed_judgment_run_id == 'J2'
    assert result.stored_overall_status == 'eligible'
    assert reason in result.reasons


def test_newest_current_basis_bad_profile_does_not_fall_back():
    old = judgment(id='old', created_at=NOW-timedelta(hours=1))
    result = resolve(jj=[old, judgment(profile_sha256='changed')])
    assert result.display_state == 'REJUDGMENT_REQUIRED'
    assert result.observed_judgment_run_id == 'J2'


@pytest.mark.parametrize('opts, reason', [
    ({'profile': None}, 'PROFILE_FRESHNESS_UNVERIFIED'),
    ({'day': None}, 'REFERENCE_DATE_NOT_REQUESTED'),
])
def test_missing_check_never_claims_complete_freshness(opts, reason):
    result = resolve(**opts)
    assert result.freshness_state == 'CHECKS_INCOMPLETE'
    assert reason in result.reasons
    assert result.stored_reference_date == DAY


def test_user_answers_are_saved_facts_not_verified_current_answers():
    result = resolve(jj=[judgment(has_user_answers=True)])
    assert result.answer_basis_check == 'UNVERIFIED'
    assert result.freshness_state == 'CHECKS_INCOMPLETE'
    assert result.selected_judgment_run_id == 'J2'


@pytest.mark.parametrize('status', ['eligible','ineligible','insufficient_data'])
def test_partial_analysis_does_not_rewrite_the_stored_verdict(status):
    result = resolve([analysis(status='PARTIAL', coverage='INCOMPLETE')],
                     [judgment(analysis_status='PARTIAL', overall_status=status)])
    assert result.display_state == 'ANALYSIS_INCOMPLETE'
    assert result.stored_overall_status == status
    assert result.judgment_state == 'AVAILABLE'


@pytest.mark.parametrize('keys', [(), ('R1','R1')])
def test_empty_or_duplicate_requirements_are_not_eligible(keys):
    result = resolve([analysis(requirement_keys=keys)])
    assert result.selected_judgment_run_id is None
    assert result.display_state in {'DATA_INVALID','ANALYSIS_INCOMPLETE'}


@pytest.mark.parametrize('change', [
    {'requirement_keys': ('R1',)}, {'requirement_keys': ('R1','R1')},
    {'requirement_keys': ('R1','R2','R3')}, {'analysis_status':'PARTIAL'},
    {'integrity_valid':False},
])
def test_bad_selected_links_are_invalid_without_fallback(change):
    result = resolve(jj=[judgment(id='old', created_at=NOW-timedelta(hours=1)), judgment(**change)])
    assert result.display_state == 'DATA_INVALID'
    assert result.selected_judgment_run_id is None


def test_unknown_reasons_do_not_leak_arbitrary_model_strings():
    result = resolve(jj=[judgment(overall_status='insufficient_data',
        unknown_reasons=('profile_missing','evidence_missing','PRIVATE_SOURCE_TEXT','profile_missing'))])
    assert result.unknown_reasons == ('evidence_missing','profile_missing')
    assert 'PRIVATE_SOURCE_TEXT' not in json.dumps(result.to_dict())


def test_order_independent_selection_and_timestamp_ties():
    aa = [analysis(id='A1'), analysis()]
    jj = [judgment(id='J1'), judgment()]
    left = resolve(aa, jj)
    assert left == resolve(list(reversed(aa)), list(reversed(jj)))
    assert left.analysis_run_id == 'A2' and left.selected_judgment_run_id == 'J2'


def test_inputs_are_immutable_and_hash_is_stable():
    aa, jj = [analysis()], [judgment()]
    before = copy.deepcopy((aa,jj))
    result = resolve(aa,jj)
    assert (aa,jj) == before
    assert result.to_dict() == resolve(aa,jj).to_dict()
    assert result.to_dict()['state_sha256'] != resolve(profile='new').to_dict()['state_sha256']


@pytest.mark.parametrize('bad', [float('nan'), object(), {'a':set([1])}])
def test_non_json_hash_input_rejected(bad):
    with pytest.raises(m.StateInputError): m.payload_fingerprint(bad)


def test_hash_preserves_unrecognized_fields_and_array_order():
    assert m.payload_fingerprint({'a':1,'b':2}) == m.payload_fingerprint({'b':2,'a':1})
    assert m.payload_fingerprint({'a':1}) != m.payload_fingerprint({'a':1,'new':2})
    assert m.payload_fingerprint([1,2]) != m.payload_fingerprint([2,1])


@pytest.mark.parametrize('options', [{'status':[]}, {'created_at':NOW.replace(tzinfo=None)}, {'coverage':[]}])
def test_invalid_snapshot_input_raises_fixed_error(options):
    with pytest.raises(m.StateInputError): analysis(**options)


def test_duplicate_ids_and_datetime_as_date_are_rejected():
    with pytest.raises(m.StateInputError): resolve([analysis(),analysis()])
    with pytest.raises(m.StateInputError): resolve(jj=[judgment(),judgment()])
    with pytest.raises(m.StateInputError): resolve(day=NOW)


def audit(**kwargs):
    coverage = dict(coverage_status='COMPLETE', candidate_count=2, processed_count=2,
        missing_candidate_ids=[], duplicate_candidate_ids=[], unknown_candidate_ids=[],
        invalid_response_indexes=[], unresolved_candidate_ids=[], needs_context_candidate_ids=[])
    coverage.update(kwargs)
    return [{'code':'REVIEW_EXECUTION_AUDIT', 'details':{'coverage':coverage,
        'plan':{'blocked':[], 'source_gaps':[]}, 'adapter_pending':[]}}]


def test_legacy_success_never_means_candidate_coverage_complete():
    assert m.coverage_from_diagnostics('SUCCEEDED',[]) == 'UNVERIFIED'
    assert m.coverage_from_diagnostics('PARTIAL',[]) == 'INCOMPLETE'
    assert m.coverage_from_diagnostics('SUCCEEDED',audit()) == 'COMPLETE'


@pytest.mark.parametrize('change', [
    {'processed_count':1}, {'candidate_count':0}, {'processed_count':True},
    {'coverage_status':[]}, {'unknown_candidate_ids':['x']}, {'duplicate_candidate_ids':['x']},
    {'missing_candidate_ids':['x']}, {'needs_context_candidate_ids':['x']},
    {'invalid_response_indexes':[0]}, {'unresolved_candidate_ids':['x']},
])
def test_contradictory_complete_audit_is_invalid(change):
    assert m.coverage_from_diagnostics('SUCCEEDED',audit(**change)) == 'INVALID'


@pytest.mark.parametrize('place, key', [('details','adapter_pending'),('plan','blocked'),('plan','source_gaps')])
def test_adaptation_and_source_gaps_cannot_be_complete(place,key):
    aa = audit()
    container = aa[0]['details'] if place=='details' else aa[0]['details']['plan']
    container[key] = ['pending']
    assert m.coverage_from_diagnostics('SUCCEEDED',aa) == 'INCOMPLETE'


def test_audit_empty_and_duplicate_contracts():
    assert m.coverage_from_diagnostics('SUCCEEDED',audit(coverage_status='EMPTY',candidate_count=0,processed_count=0)) == 'EMPTY'
    assert m.coverage_from_diagnostics('SUCCEEDED',audit()+audit()) == 'INVALID'
    assert m.coverage_from_diagnostics('SUCCEEDED',[{'code':'REVIEW_EXECUTION_AUDIT','details':None}]) == 'INVALID'


def semantic(status='SATISFIED', pending=(), role='mandatory'):
    d = NS(candidate_id='C1',status='REQUIREMENT',pending_codes=pending)
    j = NS(candidate_id='C1',status=status,pending_codes=pending,role=role,
           context_sha256='context',company_id='CO',rule_version='rule3')
    execution=NS(decisions=(d,),invalid_candidate_ids=(),
        coverage=NS(candidate_count=1,processed_count=1,coverage_status='COMPLETE'),
        plan=NS(target_candidate_ids=('C1',),blocked=(),inventory=NS(source_gaps=())))
    return NS(notice_id='N1',notice_version_id='V1',execution=execution,judgments=(j,))


@pytest.mark.parametrize('status', ['SATISFIED','UNSATISFIED','UNKNOWN'])
def test_clause_statuses_never_become_whole_notice_status(status):
    state=s.describe_semantic_state(semantic(status))
    assert state['notice_overall_status'] is None
    assert not state['full_notice_eligibility_asserted']
    assert state['semantic_coverage']=='COMPLETE'
    assert state['clause_judgment_counts'][status]==1


def test_preferred_failure_not_mandatory_failure():
    state=s.describe_semantic_state(semantic('UNSATISFIED',role='preferred'))
    assert state['mandatory_clause_count']==0 and state['notice_overall_status'] is None


def test_pending_semantics_not_profile_missing():
    state=s.describe_semantic_state(semantic('UNKNOWN',pending=('UNREPRESENTED_EXPLICIT_VALUE',)))
    assert state['semantic_coverage']=='INCOMPLETE'
    assert state['pending_candidate_count']==1


def test_semantic_missing_response_separate_from_empty():
    a=semantic(); a.execution.decisions=(); a.judgments=()
    a.execution.coverage.processed_count=0; a.execution.coverage.coverage_status='INCOMPLETE'
    state=s.describe_semantic_state(a)
    assert state['processing_state']=='INCOMPLETE'
    assert 'UNPROCESSED_CANDIDATES' in state['reasons']
    a.execution.plan.target_candidate_ids=(); a.execution.coverage.candidate_count=0
    a.execution.coverage.coverage_status='EMPTY'
    assert s.describe_semantic_state(a)['processing_state']=='EMPTY'


@pytest.mark.parametrize('mutation', ['missing_judgment','duplicate','counts','false_complete','mixed_context'])
def test_bad_semantic_links_fail_closed(mutation):
    a=semantic()
    if mutation=='missing_judgment': a.judgments=()
    if mutation=='duplicate': a.judgments*=2
    if mutation=='counts': a.execution.coverage.processed_count=0
    if mutation=='false_complete': a.execution.plan.target_candidate_ids+=('C2',); a.execution.coverage.candidate_count=2
    if mutation=='mixed_context':
        a.execution.decisions+=(NS(candidate_id='C2',status='REQUIREMENT',pending_codes=()),)
        a.execution.plan.target_candidate_ids+=('C2',)
        a.execution.coverage.candidate_count=a.execution.coverage.processed_count=2
        a.judgments+=(NS(**{**vars(a.judgments[0]),'candidate_id':'C2','context_sha256':'different'}),)
    with pytest.raises(m.StateInputError): s.describe_semantic_state(a)
