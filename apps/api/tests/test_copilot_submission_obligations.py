from apps.api.app.copilot.answer_validation import generated_draft, verify
from apps.api.app.copilot.v31_contracts import Verdicts
from apps.api.tests.test_copilot_answer_progress import setup


def test_two_stages_survive_and_all_row_fields_reach_verifier():
    _, bundle, _ = setup()
    from apps.api.app.copilot.evidence_payload import evidence_payload
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                rows = []
                for i, phase in enumerate(['입찰 등록', '계약체결']):
                    rows.append(dict(claim_id=str(i), text='표시되면 안 되는 미검증 중복 설명', fact_ids=['F2'],
                        speech_act='ASSERTION', submission=dict(document='안전보건 서약서', stage=phase,
                        obligation='필수', deadline='원문 미기재', method='방문', timing='시점 미확정',
                        conditions='두 단계의 의무를 각각 확인')))
                return schema.model_validate({'claims': rows})
            self.verified = body['claims']
            return Verdicts(verdicts=[dict(claim_id=c['claim_id'], status='CONTRADICTED', reason='방법 근거 없음') for c in body['claims']])
    gateway = Gateway()
    draft = generated_draft(gateway, 'generate', '', {'tasks': [{'kind': 'READ_DOCUMENT'}],
                            'evidence': evidence_payload(bundle)}, bundle)
    assert len(draft.claims) == 2
    assert '입찰 등록' in draft.claims[0].text and '계약체결' in draft.claims[1].text
    claims, _ = verify(draft, bundle, gateway)
    for row in gateway.verified:
        assert all(t in row['text'] for t in ['안전보건 서약서', '필수', '원문 미기재', '방문', '시점 미확정', '두 단계'])
        assert '미검증 중복 설명' not in row['text']
    assert all(c.validation == 'CONTRADICTED' for c in claims)


def test_non_document_generation_keeps_existing_schema():
    _, bundle, _ = setup()
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            assert 'submission' not in str(schema.model_json_schema())
            return schema.model_validate({'claims': []})
    assert not generated_draft(Gateway(), 'generate', '', {'tasks': [{'kind': 'READ_JUDGMENT'}]}, bundle).claims

