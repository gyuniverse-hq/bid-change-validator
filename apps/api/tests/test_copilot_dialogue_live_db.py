"""Developer scenarios, not independent human evaluation. Real API/DB/model."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.tests.test_copilot_v31_browser_live_db import live_model


def test_natural_reference_chain_and_full_source_conditions(state, authenticated_api, live_model):
    from apps.api.app.models import NoticeDocument
    db, case, _, _ = state
    rows, failures = [], []
    previous = None

    def ask(message, *, new=False, documents=False):
        nonlocal previous
        response = authenticated_api.post('/api/v1/copilot/chat',
            headers={'X-Copilot-Semantic-Processing':'true'}, json={
                'case_id':str(case.id), 'message':message, 'response_version':'3.1',
                'allow_external_processing':documents,
                'conversation_id': None if new or previous is None else previous['conversation_id'],
                'context_revision': None if new or previous is None else previous['context_revision']})
        assert response.status_code == 200, response.text
        previous = response.json()['envelope']
        rows.append({'message':message,'envelope':previous})
        return previous

    def check(condition, label):
        if not condition: failures.append(label)

    try:
        first = ask('저장된 판정의 자격요건을 순서대로 목록으로 알려줘. 원문 추가 검색이나 회사정보 요약은 필요 없어.')
        targets = [t for t in first['follow_up_targets'] if t['kind']=='REQUIREMENT' and t['ordinal']==2]
        assert len(targets)==1, 'Need an actual second displayed requirement'
        key = targets[0]['requirement_key']
        for message in ['두 번째 요건을 설명해줘.', '그 요건의 판단 이유를 알려줘.', '그 요건을 우리 회사와 비교해줘.']:
            answer = ask(message)
            check(not answer['clarification'], message + ': unambiguous target')
            keys = {t['requirement_key'] for t in answer['follow_up_targets'] if t['kind']=='REQUIREMENT'}
            check(keys == {key}, message + ': subject preserved')
            check(answer['processing']['task_status']=='PASS', message + ': completion')
            if '비교' in message:
                check(any(t['tool']=='READ_PROFILE' for t in answer['processing']['tools']), 'comparison reads profile')
            check(not answer['actions'], 'no writes proposed for explanation')

        # The four numbered conditions intentionally have different vocabulary.
        # Retrieval must not silently keep only the heading containing 참가자격.
        texts = ['1. 참가자격: 정보통신공사업 등록을 마쳐야 한다.',
                 '2. 소재지: 서울특별시에 본점을 두어야 한다.',
                 '3. 인원: 개발 인력 5명 이상을 보유해야 한다.',
                 '4. 운반 조건: 직접 운반할 수 있는 허가와 장비를 갖추어야 한다. 단, 전문 운송업체에 적법하게 위탁하면 직접 장비는 제외한다.']
        text = '\n'.join(texts)
        doc = NoticeDocument(id=uuid4(),notice_version_id=case.current_version_id,document_order=0,
            name='Synthetic multi-condition evaluation',url='https://example.invalid/synthetic',source_field='evaluation-fixture',
            extraction_status='EXTRACTED',file_sha256=hashlib.sha256(text.encode()).hexdigest(),
            extracted_text_sha256=hashlib.sha256(text.encode()).hexdigest(),extracted_text=text,
            extracted_blocks=[{'text':t,'block_index':i,'section_index':0,'location':f'clause {i+1}'} for i,t in enumerate(texts)])
        db.add(doc)
        db.commit()
        try:
            for message in ['공고문에 적힌 참가자격 전체와 예외를 빠짐없이 정리해줘.',
                            '이 문서에서 갖춰야 하는 모든 조건을 설명해줘. 위탁할 때 달라지는 점도 포함해줘.']:
                answer = ask(message,new=True,documents=True)
                prose = ' '.join(c['text'] for c in answer['claims'])
                for value in ['정보통신공사업','서울','5명','허가','장비','위탁']:
                    check(value in prose, 'full source condition missing: '+value)
                check(answer['processing']['task_status']=='PASS','full source completion')
                check(not answer['actions'],'source explanation no write')
        finally:
            db.delete(doc)
            db.commit()
    finally:
        Path(os.environ['COPILOT_DB_EVIDENCE'],'dialogue-results.json').write_text(json.dumps({
            'scope':'developer-authored synthetic cases; actual login/API/DB/model; not user evaluation',
            'rows':rows,'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
    assert not failures, failures
