from time import monotonic
from uuid import uuid4
import pytest
from apps.api.app.copilot.document_ledger import source_units, compose_document_ledger, batches
from apps.api.app.copilot.acceptance import freeze_document_acceptance
from apps.api.app.copilot.v31_contracts import Scope, Source, Fact, EvidenceBundle, TaskPlan, Task


def bundle(text):
    scope = Scope(case_id=uuid4(), company_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4())
    return EvidenceBundle(scope=scope, sources=[Source(source_id='s', kind='DOCUMENT', quote=text, scope=scope)],
        facts=[Fact(fact_id='f', kind='NOTICE_FACT', text=text, source_ids=['s'], scope=scope, origin_tool='READ_DOCUMENT')])


class Gateway:
    started = monotonic()
    deadline = started + 45
    def __init__(self, invalid=False, text='조건을 확인합니다.', tamper=False):
        self.invalid, self.text, self.tamper = invalid, text, tamper
        self.contracts = []
    def remaining(self): return 100
    def call(self, stage, system, body, schema):
        self.contracts.append(body['acceptance'])
        identity = 'changed' if self.tamper else body['acceptance']['acceptance_id']
        if stage in {'document_extract', 'document_repair'}:
            return schema(acceptance_id=identity, units=[{'unit_id': u['unit_id'], 'relevant': True, 'explanation': self.text} for u in body['units']])
        return schema(acceptance_id=identity, units=[{'unit_id': u['unit_id'], 'supported': True, 'complete': not self.invalid,
                                                   'readable': True, 'reason': '검증'} for u in body['units']])


def test_units_cover_every_character_and_keep_citations():
    text = ('등록 조건입니다. 단, 법적 예외를 확인해야 합니다.\n' * 200)
    units = source_units(bundle(text))
    spans = sorted([span for u in units for span in [u, *u.get('aliases', [])]], key=lambda u: u['start'])
    assert ''.join(text[u['start']:u['end']] for u in spans) == text
    assert all(len(u['text'].encode()) <= 3500 for u in units)
    assert all(u['fact_id'] == 'f' and u['source_id'] == 's' for u in units)


def test_reviewer_rejection_cannot_become_completed_ledger():
    b = bundle('필수 조건과 예외')
    plan = TaskPlan(goal='전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체 조건')])
    claims, partial, events = compose_document_ledger(b, plan, Gateway(invalid=True))
    assert partial and all(c.method == 'extractive' for c in claims)
    assert events[-1]['units'][0]['status'] == 'NEEDS_REVIEW'


def test_all_batches_processed_without_claim_id_collision():
    b = bundle('조건과 예외를 모두 확인합니다.\n' * 120)
    plan = TaskPlan(goal='전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체 조건')])
    claims, partial, events = compose_document_ledger(b, plan, Gateway())
    assert not partial and len({c.claim_id for c in claims}) == len(claims) > 1
    assert all(row['status'] == 'EXPLAINED' for row in events[-1]['units'])


def test_generation_validation_and_repair_share_one_frozen_deliverable():
    gateway = Gateway(invalid=True)
    plan = TaskPlan(goal='참가자격 전체와 예외를 정리해줘', tasks=[Task(kind='READ_DOCUMENT', question='전체 참가자격')])
    _, partial, events = compose_document_ledger(bundle('등록기한과 운반 예외를 확인해야 합니다.'), plan, gateway)
    assert partial and len(gateway.contracts) == 4
    assert all(c == events[-1]['acceptance'] for c in gateway.contracts)
    assert len({id(c) for c in gateway.contracts}) == 4
    assert events[-1]['acceptance']['mode'] == 'QUALIFICATIONS'
    assert any('등록기한' in item and '예외' in item for item in gateway.contracts[0]['required'])


@pytest.mark.parametrize('goal', ['참가자격과 입찰서 제출 절차 전체를 정리해줘', '공고 전체 조건과 의무를 정리해줘',
                                 '참가자격과 제출서류 전체를 정리해줘', '참가자격과 청렴 서약 의무를 정리해줘',
                                 '입찰서 작성·제출과 개찰 절차를 모두 정리해줘',
                                 '참가자격과 입찰서 작성을 정리해줘', '참가자격과 입찰서 제출을 알려줘'])
def test_broad_or_procedure_request_does_not_inherit_qualification_exclusions(goal):
    contract = freeze_document_acceptance(TaskPlan(goal=goal, tasks=[Task(kind='READ_DOCUMENT', question=goal)]))
    assert contract.mode == 'REQUEST_SCOPE' and not contract.not_required
    assert contract.request == goal


def test_submission_scope_retains_required_documents_without_demanding_bid_opening():
    goal = '입찰서 작성·제출 절차를 정리해줘. 참가자격을 설명하라는 요청은 아니야.'
    contract = freeze_document_acceptance(TaskPlan(goal=goal, tasks=[Task(kind='READ_DOCUMENT', question=goal)]))
    assert contract.mode == 'SUBMISSION'
    assert any('제출기간' in item for item in contract.required)
    assert any('개찰' in item for item in contract.not_required)


@pytest.mark.parametrize('text', ['조건은 다음 unit(u6)에 나옵니다.', '등록 조건은 u22를 확인합니다.', '조건이 필요하며 및화', '조건을 확인합니다. (미완성'])
def test_internal_ids_or_truncated_text_do_not_pass_even_when_model_approves(text):
    _, partial, events = compose_document_ledger(bundle('등록을 확인합니다.'),
        TaskPlan(goal='전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체 조건')]), Gateway(text=text))
    assert partial and events[-1]['units'][0]['status'] == 'NEEDS_REVIEW'


def test_model_cannot_replace_completion_contract():
    _, partial, events = compose_document_ledger(bundle('등록을 확인합니다.'),
        TaskPlan(goal='전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체 조건')]), Gateway(tamper=True))
    assert partial and events[-1]['units'][0]['status'] == 'NEEDS_REVIEW'


def test_many_short_spans_are_bounded_by_output_count_without_losing_units():
    units = [{'unit_id': str(i), 'text': '짧은 제목입니다.'} for i in range(65)]
    result = list(batches(units))
    assert max(map(len, result)) <= 8
    assert [u for batch in result for u in batch] == units


@pytest.mark.parametrize('invalid', [False, True])
def test_exclusions_are_reviewed_as_classifications_without_absence_claims(invalid):
    class ExclusionGateway(Gateway):
        def call(self, stage, system, body, schema):
            result = super().call(stage, system, body, schema)
            if stage in {'document_extract', 'document_repair'}:
                for answer in result.units:
                    answer.relevant = False
                    answer.explanation = '이 공고에는 참가자격이 없습니다.'
            else:
                assert all(a['explanation'] == '' for a in body['answers']['units'])
            return result
    claims, _, events = compose_document_ledger(bundle('공고 제목입니다.'),
        TaskPlan(goal='전체 참가자격', tasks=[Task(kind='READ_DOCUMENT', question='전체 참가자격')]), ExclusionGateway(invalid=invalid))
    assert all(c.method == 'extractive' for c in claims)
    assert events[-1]['units'][0]['status'] == ('NEEDS_REVIEW' if invalid else 'OUT_OF_SCOPE')
