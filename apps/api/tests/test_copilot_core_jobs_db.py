"""Approved public Core snapshots + synthetic profiles in rollback-only local DB."""
import hashlib
import json
import os
from datetime import date
from pathlib import Path
import zipfile
from collections import Counter
import pytest
from sqlalchemy.orm import Session
from apps.api.tests.test_copilot_v31_browser_live_db import live_model
from apps.api.tests.test_copilot_namwon_snapshot_db import persist_snapshot

CASES = [('R26BK01634263', 'J01', '002', '003'), ('R26BK01633750', 'J05', '000', '001'),
         ('R26BK01687120', 'J09', '000', '001')]


@pytest.mark.parametrize('notice_no,profile_id,before,after', CASES)
def test_core_job_sources_and_multiple_turns(seed_required_master_codes, live_model, notice_no, profile_id, before, after):
    from apps.api.app.database import engine
    from apps.api.app.models import PreflightCase
    from apps.api.app.scripts.seed_golden_v02_accounts import _replace_company_profile
    from apps.api.app.qualification.judgment_target import run_targeted_qualification_judgment
    from apps.api.app.copilot.chat import CopilotChatRequest
    from apps.api.app.copilot.conversation_state import ConversationRepository
    from apps.api.app.copilot.orchestration import coordinate
    from apps.api.app.copilot.tool_adapters import ProductTools
    from apps.api.app.document_rag.readiness import snapshot_sources
    root = Path(os.environ['COPILOT_CORE_SNAPSHOTS'])
    data = json.loads((root / (notice_no + '.json')).read_text(encoding='utf-8'))
    with zipfile.ZipFile(os.environ['COPILOT_CORE_PROFILES']) as archive:
        cases = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/fixture_bundle.json'))))['cases']
    profile = next(c for c in cases if c['case_id'] == profile_id)
    report = {'notice_no': notice_no, 'profile': profile_id, 'orders': [before, after],
              'scope': 'public source + synthetic profile; real PostgreSQL/coordinator/model; rollback; not browser or human evaluation',
              'snapshot_sha256': hashlib.sha256((root / (notice_no + '.json')).read_bytes()).hexdigest(),
              'source_checks': [], 'turns': []}
    output = Path(os.environ['COPILOT_DB_EVIDENCE']) / (notice_no + '-job.json')
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            objects = persist_snapshot(db, data)
            versions = {v.bid_notice_order: v for v in objects['BidNoticeVersion']}
            company = _replace_company_profile(db, profile)
            case = PreflightCase(notice_id=versions[before].notice_id, company_id=company.id,
                baseline_version_id=versions[before].id, current_version_id=versions[after].id,
                title=profile_id + ' historical Core developer evaluation ' + before + '→' + after)
            db.add(case)
            db.flush()
            analyses = {a.notice_version_id: a for a in objects['QualificationAnalysisRun']}
            for order in (before, after):
                source = snapshot_sources(versions[order])
                report['source_checks'].append({'order': order, 'status': source.source_status,
                    'records': len(source.records), 'limitations': source.limitations})
                assert source.records
            run = run_targeted_qualification_judgment(db, case_id=case.id,
                analysis_run_id=analyses[versions[after].id].id, reference_date=date.fromisoformat(profile['reference_date']))
            report['stored_result'] = {'status': run.overall_status, 'counts': dict(Counter(j.status for j in run.judgments))}
            repository, envelope = ConversationRepository(), None
            questions = ['우리 회사가 이 공고에 참여하려고 해. 현재 회사 정보로 충족하는 조건과 추가로 확인할 사항을 정리하고, 제출할 서류와 각각의 마감일·제출 방법까지 확인해서 준비 순서를 알려줘. 근거가 부족한 부분은 따로 표시해줘.',
                         '처음 부탁한 참여 준비에서 아직 확인하지 못한 항목이 정확히 뭐야? 확인할 수 있는 것은 이어서 확인하고, 끝내 확인할 수 없는 것은 이유와 내가 해야 할 행동을 알려줘. 이미 설명한 내용은 반복하지 마.']
            for question in questions:
                envelope, tools = coordinate(CopilotChatRequest(case_id=case.id, message=question,
                    response_version='3.1', allow_external_processing=True,
                    conversation_id=envelope.conversation_id if envelope else None,
                    context_revision=envelope.context_revision if envelope else None),
                    'core-developer', ProductTools(db, case, allow_documents=True), repository=repository)
                report['turns'].append({'question': question, 'envelope': envelope.model_dump(mode='json')})
                assert len(envelope.processing.calls) <= 3, 'Long review performed hidden repair/revalidation'
                assert envelope.job and envelope.job.goal == questions[0]
                assert not envelope.actions and not db.new and not db.dirty and not db.deleted
                assert envelope.status_card is None or envelope.status_card.status == run.overall_status
            report['job_complete'] = envelope.job.status == 'COMPLETE'
            report['all_turns_pass'] = all(t['envelope']['processing']['task_status'] == 'PASS' for t in report['turns'])
            first_texts = {c['text'] for c in report['turns'][0]['envelope']['claims'] if c['method']=='semantic'}
            assert not first_texts.intersection(c.text for c in envelope.claims if c.method=='semantic'), 'Continuation repeated verified prose'
            assert report['job_complete'], 'Job remains open; inspect per-requirement reasons and source limitations'
        finally:
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            db.close()
            transaction.rollback()
