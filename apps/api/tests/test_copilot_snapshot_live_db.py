"""Developer diagnostic against approved public notice snapshot, not human evaluation."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from apps.api.tests.test_copilot_v31_db import state
from apps.api.tests.test_copilot_v31_browser_live_db import live_model
from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot


def test_full_namwon_document_explanation(state, live_model):
    if not os.getenv('COPILOT_NAMWON_SNAPSHOT'):
        pytest.skip('Approved snapshot required')
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.conversation_state import ConversationRepository
    from apps.api.app.copilot.orchestration import coordinate
    from apps.api.app.copilot.tool_adapters import ProductTools
    from datetime import date
    path = Path(os.environ['COPILOT_NAMWON_SNAPSHOT'])
    data = json.loads(path.read_text(encoding='utf-8'))
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection,join_transaction_mode='create_savepoint')
        try:
            objects = persist_snapshot(db,data)
            versions = sorted(objects['BidNoticeVersion'],key=lambda v:v.version_number)
            analysis = next(a for a in objects['QualificationAnalysisRun'] if a.notice_version_id==versions[1].id)
            case = PreflightCase(notice_id=versions[0].notice_id,company_id=state[1].company_id,
                baseline_version_id=versions[0].id,current_version_id=versions[1].id,title='Public snapshot source explanation')
            db.add(case)
            db.flush()
            run_targeted_qualification_judgment(db,case_id=case.id,analysis_run_id=analysis.id,reference_date=date(2026,9,8))
            envelope,_ = coordinate(CopilotChatRequest(case_id=case.id,
                message='공고 원문에 적힌 참가자격 전체를 예외와 현장 방문 조건까지 빠짐없이 정리해줘. 회사의 참가 가능 여부를 새로 판단하라는 요청은 아니야.',
                response_version='3.1',allow_external_processing=True),
                'snapshot-developer',ProductTools(db,case,allow_documents=True),repository=ConversationRepository())
            text = ' '.join(c.text for c in envelope.claims)
            missing = [v for v in ['1257','6770','6786','1227','전북','현장','장비','허가'] if v not in text]
            Path(os.environ['COPILOT_DB_EVIDENCE'],'snapshot-model-results.json').write_text(json.dumps({
                'scope':'approved public DB extraction snapshot; synthetic company; real coordinator/PostgreSQL/model, not browser or human evaluation; outer rollback',
                'snapshot_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'missing_terms':missing,
                'envelope':envelope.model_dump(mode='json')},ensure_ascii=False,indent=2),encoding='utf-8')
            assert not missing, missing
            assert envelope.processing.task_status=='PASS'
        finally:
            db.close()
            outer.rollback()
