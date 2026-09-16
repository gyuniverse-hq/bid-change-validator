from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from apps.api.tests.test_copilot_answer_progress import setup
from apps.api.app.copilot.document_memory import remember_documents, restore_documents


def seeded():
    state, bundle, plan = setup()
    bundle.fingerprints['document'] = 'same-complete-source'
    bundle.coverage['READ_DOCUMENT'] = 'FOUND'
    remember_documents(state, bundle, [NS(validation='SUPPORTED', method='semantic', fact_ids=['document'])])
    return state, bundle


def test_followup_retrieval_keeps_previously_verified_deadline_source():
    state, bundle = seeded()
    bundle.facts = [f for f in bundle.facts if f.fact_id != 'document']
    bundle.sources = [s for s in bundle.sources if s.source_id != 'document']
    assert restore_documents(state, bundle) == 1
    assert any('15시' in f.text for f in bundle.facts)
    assert restore_documents(state, bundle) == 0
    remember_documents(state, bundle, [])
    assert state.document_memory['facts']


@pytest.mark.parametrize('change', ['fingerprint', 'scope', 'optout', 'unavailable'])
def test_stale_or_unauthorized_source_cannot_be_reused(change):
    state, bundle = seeded()
    bundle.facts = []; bundle.sources = []
    if change == 'fingerprint': bundle.fingerprints['document'] = 'changed'
    elif change == 'scope': bundle.scope = bundle.scope.model_copy(update={'company_id':uuid4()})
    elif change == 'optout': bundle.fingerprints = {}
    else: bundle.coverage['READ_DOCUMENT'] = 'UNAVAILABLE'
    assert restore_documents(state, bundle) == 0
    assert not bundle.facts and not bundle.sources


def test_extractive_fallback_and_unverified_prose_do_not_enter_memory():
    state, bundle, plan = setup(); bundle.fingerprints['document'] = 'same'
    remember_documents(state, bundle, [NS(validation='SUPPORTED', method='extractive', fact_ids=['document']),
                                      NS(validation='INSUFFICIENT', method='semantic', fact_ids=['document'])])
    assert not state.document_memory['facts']


def test_full_notice_above_old_cap_preserves_deadline_and_reports_actual_overflow():
    from apps.api.app.copilot.document_memory import MAX_MEMORY_BYTES
    state, bundle, _ = setup()
    bundle.fingerprints['document'] = 'current-whole-source'
    # Source and fact contain the same public excerpt, including its deadline.
    text = '제안서 마감 7월 27일 15시. ' + '제출 원문 조항. ' * 5000
    bundle.facts[1].text = bundle.sources[1].quote = text
    claim = NS(validation='SUPPORTED', method='semantic', fact_ids=['document'])
    remember_documents(state, bundle, [claim])
    import json
    size = len(json.dumps(state.document_memory, ensure_ascii=False).encode())
    assert 160000 < size < MAX_MEMORY_BYTES
    bundle.facts = []; bundle.sources = []
    assert restore_documents(state, bundle) == 1
    assert bundle.facts[0].text == bundle.sources[0].quote == text
    bundle.facts[0].text = bundle.sources[0].quote = text * 4
    remember_documents(state, bundle, [claim])
    assert state.document_memory['status'] == 'OVERFLOW'
    bundle.facts = []; bundle.sources = []
    assert restore_documents(state, bundle) == 0
    assert bundle.server_context['document_memory']['status'] == 'OVERFLOW'
    assert any('보관 한도' in line for line in bundle.limitations)
