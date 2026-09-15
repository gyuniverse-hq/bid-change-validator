from types import SimpleNamespace
import pytest
from apps.api.tests.test_copilot_document_ledger import bundle
from apps.api.app.copilot.v31_contracts import Claim
from apps.api.app.copilot.answer_integration import integrate_verified_claims


@pytest.mark.parametrize('failure', [None, 'missing_id', 'unsupported', 'omitted_exception', 'wrong_id'])
def test_summary_keeps_every_verified_condition_or_preserves_original_notes(failure):
    evidence = bundle('전자입찰은 14시까지, 방문 제출은 15시까지입니다. 방문 제출만 대리인 위임장을 요구합니다.')
    claims = [Claim(claim_id='a', text='전자입찰은 14시까지입니다.', fact_ids=['f'], source_ids=['s'], validation='SUPPORTED'),
              Claim(claim_id='b', text='방문 제출은 15시까지이며 대리인은 위임장이 필요합니다.', fact_ids=['f'], source_ids=['s'], validation='SUPPORTED')]
    class Gateway:
        def call(self, stage, system, body, schema):
            if stage == 'integration_generate':
                ids = ['n0'] if failure == 'missing_id' else ['n0', 'invented'] if failure == 'wrong_id' else ['n0', 'n1']
                return schema(sections=[{'text': '전자입찰은 14시, 방문 제출은 15시까지이며 대리인은 위임장이 필요합니다.', 'note_ids': ids}])
            return schema(supported=failure != 'unsupported', complete=failure != 'omitted_exception',
                          readable=True, missing_note_ids=['n1'] if failure == 'omitted_exception' else [], reason='test')
    result, complete, events = integrate_verified_claims(claims, SimpleNamespace(goal='제출 준비'), evidence, Gateway())
    assert complete is (failure is None)
    if failure:
        assert result == claims and events[-1]['status'] == 'PARTIAL'
    else:
        assert len(result) == 1 and result[0].source_ids == ['s'] and '위임장' in result[0].text


def test_unreviewed_extract_does_not_enter_synthesis():
    evidence = bundle('원문')
    claim = Claim(claim_id='q', text='원문', fact_ids=['f'], source_ids=['s'], validation='SUPPORTED', method='extractive')
    result, complete, _ = integrate_verified_claims([claim], None, evidence, None)
    assert result == [claim] and not complete
