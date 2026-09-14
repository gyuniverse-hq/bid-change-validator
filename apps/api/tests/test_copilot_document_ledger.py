from time import monotonic
from uuid import uuid4
from apps.api.app.copilot.document_ledger import source_units, compose_document_ledger
from apps.api.app.copilot.v31_contracts import Scope, Source, Fact, EvidenceBundle, TaskPlan, Task


def bundle(text):
    scope = Scope(case_id=uuid4(), company_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4())
    return EvidenceBundle(scope=scope, sources=[Source(source_id='s', kind='DOCUMENT', quote=text, scope=scope)],
        facts=[Fact(fact_id='f', kind='NOTICE_FACT', text=text, source_ids=['s'], scope=scope, origin_tool='READ_DOCUMENT')])


class Gateway:
    started = monotonic()
    deadline = started + 45
    def __init__(self, invalid=False): self.invalid = invalid
    def remaining(self): return 100
    def call(self, stage, system, body, schema):
        if stage in {'document_extract', 'document_repair'}:
            return schema(units=[{'unit_id': u['unit_id'], 'relevant': True, 'explanation': '조건을 확인합니다.'} for u in body['units']])
        return schema(units=[{'unit_id': u['unit_id'], 'supported': True, 'complete': not self.invalid, 'reason': '검증'} for u in body['units']])


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
