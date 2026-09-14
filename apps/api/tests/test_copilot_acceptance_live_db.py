"""Budgeted repeated model evaluation with full synthetic candidate/verification traces."""
import hashlib
import json
import os
from pathlib import Path
import pytest
from apps.api.tests.test_copilot_v31_db import state, authenticated_api
from apps.api.app.copilot.model_gateway import ModelGateway, BudgetExceeded


def test_repeated_dialogue_and_adversarial_controls(state, authenticated_api, monkeypatch):
    if not os.getenv('COPILOT_LIVE_MAX_USD'):
        pytest.skip('Explicit budgeted live-model runner required')
    from apps.api.app.copilot import orchestration
    from apps.api.app.copilot.answer_validation import verify
    from apps.api.app.copilot.tool_adapters import ProductTools
    from apps.api.app.copilot.v31_contracts import Draft, DraftClaim, Task, TaskPlan
    cap = float(os.environ['COPILOT_LIVE_MAX_USD'])
    output = Path(os.environ['COPILOT_DB_EVIDENCE'])
    reserved, calls, rows, traces, failures, gateways = [0.0], [], [], [], [], []
    def save():
        cost = sum((c['usage']['prompt_tokens'] * 0.20 + c['usage']['completion_tokens'] * 1.20) / 1_000_000
                   if c.get('usage') else 0.0068 for c in calls)
        output.joinpath('live-results.json').write_text(json.dumps({'rows': rows, 'calls': calls,
            'failures': failures, 'reserved_upper_usd': reserved[0], 'usage_upper_usd': cost,
            'scope': 'real login/ASGI/API/DB/model; synthetic persisted data'}, ensure_ascii=False, indent=2), encoding='utf-8')
        output.joinpath('model-traces.json').write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding='utf-8')
    class BudgetedGateway(ModelGateway):
        def call(self, stage, system, body, schema):
            if reserved[0] + 0.0068 > cap:
                raise BudgetExceeded('EVAL_USD_BUDGET')
            reserved[0] += 0.0068
            trace = {'stage': stage, 'system': system, 'input': body,
                'acceptance_sha256': hashlib.sha256(json.dumps(body.get('acceptance'), sort_keys=True).encode()).hexdigest()}
            traces.append(trace)
            try:
                result = super().call(stage, system, body, schema)
                trace['output'] = result.model_dump(mode='json')
                return result
            except Exception as error:
                trace['error_type'] = type(error).__name__
                raise
            finally:
                calls[:] = [c for g in gateways for c in g.calls]
                save()
    def factory():
        g = BudgetedGateway(model='gpt-5.6-luna'); gateways.append(g); return g
    monkeypatch.setattr(orchestration, 'ModelGateway', factory)
    db, case, _, run = state
    def check(condition, name):
        if not condition: failures.append(name)
    try:
        for repeat in range(3):
            envelope = None
            for question in ['현재 추가 답변이 필요한 확인 질문을 알려줘.', '판정에 사용한 회사정보만 요약해줘.']:
                response = authenticated_api.post('/api/v1/copilot/chat', headers={'X-Copilot-Semantic-Processing': 'true'}, json={
                    'case_id': str(case.id), 'message': question, 'response_version': '3.1',
                    'conversation_id': envelope['conversation_id'] if envelope else None,
                    'context_revision': envelope['context_revision'] if envelope else None})
                label = f'repeat-{repeat + 1}: {question}'
                check(response.status_code == 200, label + ':HTTP')
                if response.status_code != 200:
                    rows.append({'label': label, 'http_status': response.status_code}); continue
                envelope = response.json()['envelope']
                rows.append({'label': label, 'envelope': envelope})
                check(bool(envelope['claims']) and not envelope['clarification'], label + ':answer')
                check(any(c['method'] == 'semantic' for c in envelope['claims']), label + ':semantic')
                check(envelope['processing']['task_status'] == 'PASS', label + ':completion')
                check(not envelope['actions'], label + ':no-write')
                text = ' '.join(c['text'] for c in envelope['claims'])
                if '확인 질문' in question:
                    check('정보통신공사업' in text and ('6억' in text or '600,000,000' in text), label + ':required-conditions')
                else:
                    check('서울' in text and '8' in text and ('5억' in text or '500,000,000' in text), label + ':profile-values')
                save()
                print(label + ': ' + envelope['processing']['task_status'], flush=True)
        tools = ProductTools(db, case); tools.required_checks()
        facts = tools.bundle.facts
        assert len(facts) == 2 and '6억' in facts[0].text
        questions = [DraftClaim(claim_id='q' + str(i), text=f.text, fact_ids=[f.fact_id],
            source_ids=f.source_ids, speech_act='CHECK_REQUEST') for i, f in enumerate(facts)]
        plan = TaskPlan(goal='확인할 질문을 모두 알려줘', tasks=[Task(kind='READ_CHECKS', question='확인 질문 목록')])
        controls = [('questions-complete', questions, 'COMPLETE'), ('question-omitted', questions[:1], 'PARTIAL'),
            ('false-assertion-as-question', [questions[0].model_copy(update={
                'text': '귀사는 최근 3년간 공공기관 실적 6억 원 이상을 이미 충족합니다.'}), questions[1]], 'PARTIAL'),
            ('wrong-threshold-question', [questions[0].model_copy(update={
                'text': questions[0].text.replace('6억', '7억')}), questions[1]], 'PARTIAL')]
        for name, candidates, expected in controls:
            claims, events = verify(Draft(claims=candidates), tools.bundle, factory(), plan=plan)
            coverage = next((e['task_coverage'] for e in events if 'task_coverage' in e), 'UNKNOWN')
            check(coverage == expected, name + ':coverage')
            if name in {'false-assertion-as-question', 'wrong-threshold-question'}:
                check(claims[0].validation != 'SUPPORTED', name + ':reject')
            rows.append({'label': name, 'expected': expected, 'coverage': coverage,
                         'claims': [c.model_dump() for c in claims], 'events': events})
            save()
        # Separate fixed-source controls (not DB reads) preserve all numeric
        # conditions while omitting only the exceptions in the negative case.
        from apps.api.tests.test_copilot_v31 import bundle as fixed_bundle
        b = fixed_bundle()
        b.facts = [f for f in b.facts if f.fact_id == 'exception']
        b.sources = [s for s in b.sources if s.source_id == 's-exception']
        p = TaskPlan(goal='실적의 전체 조건과 제외 기관을 설명해줘', tasks=[
            Task(kind='READ_DOCUMENT', question='실적의 전체 조건과 제외 기관을 빠짐없이 설명해줘')])
        for name, text, expected in [
            ('all-conditions-and-exceptions', b.sources[0].quote, 'COMPLETE'),
            ('exception-omitted', '공고일 기준 2년 내 2개 이상 단체급식소에서 1일 평균 800식 이상을 1년 이상 운영한 실적이 필요합니다.', 'PARTIAL')]:
            d = Draft(claims=[DraftClaim(claim_id='doc', text=text, fact_ids=['exception'], source_ids=['s-exception'])])
            claims, events = verify(d, b, factory(), plan=p)
            coverage = next((e['task_coverage'] for e in events if 'task_coverage' in e), 'UNKNOWN')
            check(coverage == expected, name + ':coverage')
            check(claims[0].validation == 'SUPPORTED', name + ':truth')
            rows.append({'label': name, 'scope': 'fixed synthetic source, no DB read', 'expected': expected,
                         'coverage': coverage, 'claims': [c.model_dump() for c in claims], 'events': events})
            save()
        # Remove only this disposable fixture's judgment to test truly absent DB data.
        db.delete(run); db.commit()
        response = authenticated_api.post('/api/v1/copilot/chat', headers={'X-Copilot-Semantic-Processing': 'true'}, json={
            'case_id': str(case.id), 'message': '판정에 사용한 회사정보만 요약해줘.', 'response_version': '3.1'})
        check(response.status_code == 200, 'missing-db-basis:HTTP')
        if response.status_code == 200:
            envelope = response.json()['envelope']
            check(envelope['processing']['task_status'] != 'PASS', 'missing-db-basis:completion')
            check(not any(c['method'] == 'semantic' for c in envelope['claims']), 'missing-db-basis:no-invention')
            rows.append({'label': 'missing-db-basis', 'envelope': envelope})
    finally:
        save()
    assert not failures, failures
