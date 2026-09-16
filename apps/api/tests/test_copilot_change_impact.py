from datetime import date
from types import SimpleNamespace as NS
import pytest
from apps.api.app.copilot.change_impact import compare_saved_impact, impact_text
from apps.api.app.qualification.rules.judgment import RULE_VERSION


def test_provenance_only_modification_is_not_a_structured_condition_change():
    from copy import deepcopy
    from apps.api.app.copilot.change_impact import structured_change_kind
    before=NS(type='INDUSTRY',operator='MATCH',value='1224',scope={'source_contract':{'raw_sha256':'old','kind':'WASTE_TRANSPORT'},'source_group':{'relation':'AND','source_fingerprint':'old'}})
    after=deepcopy(before);after.scope['source_contract']['raw_sha256']='new';after.scope['source_group']['source_fingerprint']='new'
    change=NS(baseline=before,current=after)
    assert structured_change_kind(change)=='STRUCTURED_VALUE_SAME'
    after.value='1227'
    assert structured_change_kind(change)=='STRUCTURED_VALUE_CHANGED'
    after.value='1224';after.scope['source_group']['relation']='OR'
    assert structured_change_kind(change)=='STRUCTURED_VALUE_CHANGED'
    after.scope=deepcopy(before.scope);after.scope['unknown_decision_field']=True
    assert structured_change_kind(change)=='STRUCTURED_VALUE_CHANGED'
    assert before.scope['source_contract']['raw_sha256']=='old'
    assert structured_change_kind(NS(baseline=before,current=None))=='REMOVED'


def sample():
    p = NS(case_id='case', company_id='company',
           baseline=NS(judgment_run_id='j1', analysis_run_id='a1', notice_version_id='v1', analysis_status='PARTIAL'),
           current=NS(judgment_run_id='j2', analysis_run_id='a2', notice_version_id='v2', analysis_status='PARTIAL'))
    runs = []
    for index, version in enumerate((p.baseline, p.current)):
        runs.append(NS(id=version.judgment_run_id, preflight_case_id='case', company_id='company',
                       analysis_run_id=version.analysis_run_id, notice_version_id=version.notice_version_id,
                       analysis_status='PARTIAL', reference_date=date(2026, 8, 18), rule_version=RULE_VERSION,
                       profile_snapshot={'company_id':'company','industries':[{'code':'1227'}]},
                       overall_status='ineligible', judgments=[NS(requirement_key='industry',status='UNKNOWN' if index==0 else 'SATISFIED',basis_type='PROFILE'),
                           NS(requirement_key='registration',status='UNSATISFIED',basis_type='PROFILE')]))
    lineage = NS(id='r1', preflight_case_id='case', source_judgment_run_id='j1',result_judgment_run_id='j2',
                 baseline_analysis_run_id='a1',current_analysis_run_id='a2',revalidated_keys=['industry'])
    changes = [NS(baseline_key=key,current_key=key,change_type='MODIFIED' if key=='industry' else 'UNCHANGED',
                  baseline=NS(type='INDUSTRY',raw='등록',value='1224',scope={}),current=NS(type='INDUSTRY',raw='등록',value='1227',scope={}))
               for key in ('industry','registration')]
    return lineage, *runs, p, changes


def test_individual_improvement_does_not_imply_overall_eligibility_reversal():
    impact = compare_saved_impact(*sample())
    assert impact['available'] and impact['profile_equal'] and impact['partial']
    assert impact['before_status'] == impact['after_status'] == 'ineligible'
    assert impact['rows'][0]['before_status']=='UNKNOWN'
    assert impact['rows'][0]['after_status']=='SATISFIED'
    assert impact['rows'][1]['before_status']==impact['rows'][1]['after_status']=='UNSATISFIED'
    assert '참가 불가 → 참가 불가' in impact_text(impact)
    assert impact['profile_industry_codes']==['1227']


@pytest.mark.parametrize('field,value', [('company_id','foreign'),('preflight_case_id','foreign'),
    ('notice_version_id','old'),('analysis_run_id','old'),('id','old'),('analysis_status','SUCCEEDED'),
    ('rule_version','previous-rule'),('reference_date',date(2026,8,19)),
    ('profile_snapshot',{'company_id':'company','industries':[]})])
def test_mismatched_comparison_is_unavailable(field,value):
    args=sample()
    setattr(args[2],field,value)
    assert not compare_saved_impact(*args)['available']


def test_missing_lineage_and_incomplete_judgments_do_not_invent_history():
    args=list(sample());args[0]=None
    assert not compare_saved_impact(*args)['available']
    args=list(sample());args[1].judgments.pop()
    assert not compare_saved_impact(*args)['available']


def test_same_profile_changed_on_both_runs_changes_fingerprint():
    args=sample();original=compare_saved_impact(*args)
    for run in args[1:3]:run.profile_snapshot['industries'].append({'code':'1257'})
    revised=compare_saved_impact(*args)
    assert revised['profile_sha256']!=original['profile_sha256']


def test_individual_status_does_not_resolve_industry_group_relation():
    args=sample()
    args[-1][0].current.scope={'source_group':{'relation':'UNRESOLVED'}}
    result=compare_saved_impact(*args)
    assert result['available'] and result['group_relation_unresolved']
    assert '결합 관계(AND/OR)는 미확정' in impact_text(result)


def test_impact_acceptance_requires_paired_fact_and_not_execution():
    from apps.api.app.copilot.acceptance import freeze_acceptance
    from apps.api.app.copilot.v31_contracts import EvidenceBundle, Fact, Scope, Task, TaskPlan
    from uuid import uuid4
    scope=Scope(case_id=uuid4(),company_id=uuid4(),notice_id=uuid4(),notice_version_id=uuid4())
    fact=Fact(fact_id='impact',kind='SERVER_RESULT',text='같은 기준의 전후 판정',source_ids=['source'],scope=scope,
              origin_tool='READ_CHANGES',entity_ref='saved_change_impact')
    criteria=freeze_acceptance(TaskPlan(goal='공고 변경으로 우리 회사 판정이 바뀌었어?',tasks=[Task(kind='READ_CHANGES',question='변경 영향')]),
                               EvidenceBundle(scope=scope,facts=[fact]))
    impact=next(c for c in criteria if c.criterion_id=='READ_CHANGES:impact')
    assert impact.fact_ids==('impact',)
    assert '기준/현재' in impact.requirement and '기존부터 남은 미달' in impact.requirement
