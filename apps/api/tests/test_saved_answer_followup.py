import hashlib
import json
from types import SimpleNamespace as NS
import pytest
from apps.api.app.copilot.saved_answer_followup import followup_kind, receipt_text
from apps.api.app.ai.contracts import QualificationRequirement
from apps.api.app.qualification.rules.source_contracts import VERSION


@pytest.mark.parametrize('message,expected', [
    ('방금 반영한 내용과 현재 판정을 설명해줘','receipt'),
    ('방금 저장한 답변 때문에 어떤 요건이 바뀌었어? 전체 판정이 그대로라면 그 이유도 짧게 설명해줘.', 'receipt'),
    ('확인서를 제출했다고 가정하면 어떻게 돼?','assumption'),
    ('아까 답변을 잘못했어. 수정하려면 어떻게 해야 해?','correction'),
    ('공고 변경 내용을 설명해줘',None),
    ('입찰서를 수정하려면 어떻게 해야 해?',None),
    ('방금 반영한 내용과 현재 판정을 설명해줘. 그리고 저장해줘',None),
])
def test_user_answer_scope_is_not_notice_change_or_bid_submission(message, expected):
    assert followup_kind(message) == expected


def fixture():
    raw='현장 방문 확인서 제출 업체에 한하여 입찰 참가를 인정한다.'
    basis=hashlib.sha256(raw.encode()).hexdigest()
    requirement=QualificationRequirement(requirement_key='visit',notice_version_id='v2',type='REGISTRATION_CERTIFICATION',operator='MATCH',value='현장 방문',raw=raw,evidence_keys=['ev'],condition_complexity='composite',scope={'source_contract':{'version':VERSION,'kind':'SITE_VISIT','raw_sha256':basis}})
    answer=NS(requirement_key='visit', normalized_value=json.dumps({'basis':basis,'answers':{'site_visited':True,'visit_certificate':False}}),answer_json={'satisfies_requirement':False})
    summary=NS(judgments=[NS(requirement_key='visit',status='UNSATISFIED',raw=raw),NS(requirement_key='registration',status='UNSATISFIED',raw='나라장터 등록 요건')],judgment_counts={'SATISFIED':3,'UNKNOWN':0,'UNSATISFIED':2},overall_status='ineligible')
    source=NS(judgments=[NS(requirement_key='visit',status='UNKNOWN')])
    return summary,answer,source,requirement


def test_receipt_assumption_correction_keep_stored_truth_and_no_write_claim():
    args=fixture()
    receipt=receipt_text('receipt',*args)
    assert '확인서 미제출' in receipt and '확인 필요에서 미달' in receipt and '미달 2건' in receipt
    assumption=receipt_text('assumption',*args)
    assert '나라장터 등록 요건' in assumption and '전체 참가 가능이라고 할 수 없습니다' in assumption
    assert '재판정은 하지 않았습니다' in assumption
    correction=receipt_text('correction',*args)
    assert '직접 수정하는 기능이 없습니다' in correction and '입찰서 수정 금지 조항과는 다른 문제' in correction


def test_receipt_wrong_basis_is_not_promoted_to_saved_visit_fact():
    from apps.api.app.qualification.judgment import QualificationJudgmentError
    args=fixture()
    args[1].normalized_value=args[1].normalized_value.replace('"basis": "','"basis": "wrong')
    with pytest.raises(QualificationJudgmentError):
        receipt_text('receipt',*args)


def test_no_receipt_does_not_invent_recent_change():
    assert '찾지 못했습니다' in receipt_text('receipt',fixture()[0],None,None,None)
