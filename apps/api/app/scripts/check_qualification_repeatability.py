"""동일한 공고·회사 스냅샷으로 구/신 추출 경로의 반복성을 측정한다.

실제 DB는 PostgreSQL READ ONLY로 한 번만 읽는다. 분석/판정 결과를 DB에 저장하지
않으며 --live-model을 명시하지 않으면 LLM을 호출하지 않는다. 안정성은 정확도가 아니다.
회사 상세와 원문/모델 응답은 보고서에 넣지 않고 지문/건수/진단만 남긴다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

PROBE_VERSION = 'qualification-repeatability-v1'
STRATEGIES = ('legacy', 'review_v1', 'review_graph_v1')


class ProbeError(ValueError):
    """고정 코드만 기록한다. DB 주소나 예외 원문을 출력하지 않는다."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def semantic_payload(requirement) -> dict:
    return {key: getattr(requirement, key) for key in ('type', 'operator', 'value', 'unit',
        'period_months', 'scope', 'requirement_role', 'required', 'condition_complexity')}


def canonical_signature(requirements) -> str:
    """표시 ID는 제외하지만 그룹별 연결·연산자·기간·scope·중복은 보존한다."""
    groups = {}
    for req in requirements:
        groups.setdefault(req.requirement_group_key or req.requirement_key, []).append({
            'operator': req.group_operator or 'ALL_OF', 'predicate': semantic_payload(req)})
    normalized = [sorted(items, key=digest) for items in groups.values()]
    return digest(sorted(normalized, key=digest))


@dataclass(frozen=True)
class CapturedCase:
    case_id: str
    notice_number: str
    profile: Any
    versions: tuple[dict[str, Any], ...]

    def manifest(self) -> dict:
        return {'case_sha256': digest(self.case_id), 'notice_number': self.notice_number,
            'profile_sha256': digest(self.profile.model_dump(mode='json')),
            'versions': [{key: value for key, value in item.items() if key != 'input'}
                         for item in self.versions]}


def capture_case(engine, case_id: UUID, expected_notice: str) -> CapturedCase:
    """새 세션의 첫 문장을 읽기 전용으로 설정한다. 호출자의 작업 세션을 사용하지 않는다."""
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session, selectinload
    from apps.api.app.models import BidNotice, BidNoticeVersion, PreflightCase
    from apps.api.app.judgment_models import CompanyQualificationProfileCompleteness
    from apps.api.app.qualification.analysis import build_qualification_analysis_input
    from apps.api.app.qualification.judgment import _load_company, _record_to_completeness, build_company_profile_snapshot

    if engine.dialect.name != 'postgresql':
        raise ProbeError('POSTGRESQL_READ_ONLY_REQUIRED')
    with Session(engine, autoflush=False) as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        case = db.get(PreflightCase, case_id)
        if case is None or case.company_id is None:
            raise ProbeError('CASE_OR_COMPANY_NOT_FOUND')
        notice = db.get(BidNotice, case.notice_id)
        if notice is None or notice.bid_notice_no != expected_notice:
            raise ProbeError('NOTICE_TARGET_MISMATCH')
        company = _load_company(db, case.company_id)
        completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, case.company_id))
        profile = build_company_profile_snapshot(company, completeness).model_copy(deep=True)
        ids = [('current', case.current_version_id)]
        if case.baseline_version_id and case.baseline_version_id != case.current_version_id:
            ids.insert(0, ('baseline', case.baseline_version_id))
        captured = []
        for role, version_id in ids:
            version = db.scalar(select(BidNoticeVersion).where(BidNoticeVersion.id == version_id)
                .options(selectinload(BidNoticeVersion.documents)))
            if version is None or version.notice_id != case.notice_id:
                raise ProbeError('NOTICE_VERSION_MISMATCH')
            source = build_qualification_analysis_input(version).model_copy(deep=True)
            posted = version.posted_at
            notice_day = (posted.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
                          if posted and posted.tzinfo else None)
            captured.append({'role': role, 'version_number': version.version_number,
                'notice_version_id': str(version.id), 'source_order': version.bid_notice_order,
                'input': source, 'input_sha256': digest(source.model_dump(mode='json')),
                'notice_date': notice_day, 'document_count': len(version.documents),
                'extracted_document_count': len(source.documents),
                'block_count': sum(len(doc.extracted_blocks) for doc in source.documents),
                'source_documents': [{'id': str(doc.id), 'status': doc.extraction_status,
                    'file_sha256': doc.file_sha256, 'text_sha256': doc.extracted_text_sha256}
                    for doc in sorted(version.documents, key=lambda doc: str(doc.id))]})
        db.rollback()
    return CapturedCase(str(case_id), expected_notice, profile, tuple(captured))


class BudgetedExtractor:
    """전체 실행의 호출 상한. 모델 오류 원문·회사·원문은 기록하지 않는다."""
    def __init__(self, delegate, maximum: int):
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 200:
            raise ProbeError('INVALID_CALL_BUDGET')
        self.delegate, self.maximum, self.calls = delegate, maximum, 0
        self.events = []
        self.model = getattr(delegate, 'model', None)

    def __call__(self, prompt, body, schema):
        if self.calls >= self.maximum:
            raise ProbeError('MODEL_CALL_BUDGET_EXHAUSTED')
        self.calls += 1
        event = {'call': self.calls, 'prompt_sha256': digest(prompt), 'body_sha256': digest(body),
                 'schema_sha256': digest(schema), 'body_chars': len(body)}
        self.events.append(event)
        started = time.monotonic()
        try:
            result = self.delegate(prompt, body, schema)
            event.update(status='RETURNED', response_sha256=digest(result))
            return result
        except Exception:
            event['status'] = 'ERROR'
            raise
        finally:
            event['elapsed_ms'] = round((time.monotonic() - started) * 1000, 2)


def summarize_repeats(rows: list[dict], expected_runs: int) -> list[dict]:
    summaries = []
    for key in sorted({(row['strategy'], row['role']) for row in rows}):
        items = [row for row in rows if (row['strategy'], row['role']) == key]
        succeeded = [row for row in items if row['execution'] == 'RETURNED']
        summaries.append({'strategy': key[0], 'role': key[1], 'expected_runs': expected_runs,
            'returned_runs': len(succeeded), 'error_runs': len(items)-len(succeeded),
            'semantic_variant_count': len({row['semantic_sha256'] for row in succeeded}),
            'judgment_variant_count': len({row['judgment_sha256'] for row in succeeded}),
            'same_semantics': len(succeeded) == expected_runs and len({row['semantic_sha256'] for row in succeeded}) == 1,
            'same_judgments': len(succeeded) == expected_runs and len({row['judgment_sha256'] for row in succeeded}) == 1,
            'accuracy': None, 'accuracy_note': '동일한 오답도 안정적일 수 있다. 검수 정답과의 정확도 평가는 별도다.'})
    return summaries


def measure(capture: CapturedCase, *, reference_date: date, extractor: BudgetedExtractor,
            runs: int = 3, strategies: tuple[str, ...] = STRATEGIES) -> dict:
    from apps.api.app.ai.qualification.extraction.analysis_pipeline import analyze_qualification_documents
    from apps.api.app.ai.qualification.extraction.review_execution import ReviewOptions
    from apps.api.app.qualification.rules.judgment import judge_requirements
    from apps.api.app.qualification.semantic_state import analyze_semantics_with_state

    if isinstance(runs, bool) or not isinstance(runs, int) or not 2 <= runs <= 10:
        raise ProbeError('REPEAT_COUNT_MUST_BE_2_TO_10')
    if not isinstance(reference_date, date) or isinstance(reference_date, datetime):
        raise ProbeError('EXPLICIT_REFERENCE_DATE_REQUIRED')
    if not strategies or len(set(strategies)) != len(strategies) or set(strategies)-set(STRATEGIES):
        raise ProbeError('INVALID_STRATEGIES')
    if any(not version['input'].documents for version in capture.versions):
        raise ProbeError('EXTRACTED_DOCUMENTS_REQUIRED')
    rows = []
    for index in range(runs):
        for version in capture.versions:
            for strategy in strategies:
                row = {'run': index+1, 'role': version['role'], 'strategy': strategy,
                       'input_sha256': version['input_sha256']}
                try:
                    source = version['input'].model_copy(deep=True)
                    profile = capture.profile.model_copy(deep=True)
                    if strategy == 'review_graph_v1':
                        dates = {'NOTICE_DATE': date.fromisoformat(version['notice_date'])} if version['notice_date'] else {}
                        result = analyze_semantics_with_state(source, structured_extract=extractor,
                            profile=profile, preflight_case_id=capture.case_id, reference_date=reference_date,
                            anchor_dates=dates, options=ReviewOptions(max_calls=extractor.maximum))
                        audit = result.analysis.audit()
                        semantic = [(d.candidate_id, d.status, d.audit().get('semantic_sha256'), list(d.pending_codes))
                                    for d in result.analysis.execution.decisions]
                        decisions = [(j.candidate_id, j.status, j.semantic_sha256, list(j.pending_codes))
                                     for j in result.analysis.judgments]
                        row.update(analysis_status=result.state['semantic_coverage'],
                            requirement_count=sum(len(d.atoms) for d in result.analysis.execution.decisions),
                            semantic_sha256=digest(sorted(semantic)), judgment_sha256=digest(sorted(decisions)),
                            notice_overall_status=None, state=result.state, audit=audit)
                    else:
                        options = {'review_options': ReviewOptions(max_calls=extractor.maximum)} if strategy == 'review_v1' else {}
                        result = analyze_qualification_documents(source, structured_extract=extractor,
                            extraction_strategy=strategy, **options)
                        judged = judge_requirements(result.requirements, profile, preflight_case_id=capture.case_id,
                                                    reference_date=reference_date, analysis_status=result.status)
                        by_key = {req.requirement_key: semantic_payload(req) for req in result.requirements}
                        row.update(analysis_status=result.status, requirement_count=len(result.requirements),
                            semantic_sha256=canonical_signature(result.requirements),
                            judgment_sha256=digest(sorted([(digest(by_key[j.requirement_key]), j.status)
                                                           for j in judged.judgments])),
                            notice_overall_status=judged.overall_status,
                            diagnostic_codes=sorted({d.code for d in result.diagnostics}),
                            dropped_count=len(result.dropped_requirements))
                    row['execution'] = 'RETURNED'
                except Exception as error:
                    row.update(execution='ERROR', error_code=str(error) if isinstance(error, ProbeError) else 'PIPELINE_EXECUTION_ERROR')
                rows.append(row)
    return {'probe_version': PROBE_VERSION, 'mode': 'PROVIDER_CALLS', 'manifest': capture.manifest(),
        'reference_date': reference_date.isoformat(), 'model': extractor.model, 'model_calls': extractor.calls,
        'call_budget': extractor.maximum, 'call_events': extractor.events, 'rows': rows,
        'summary': summarize_repeats(rows, runs), 'db_writes': False, 'quality_verdict': 'NOT_ESTABLISHED',
        'graph_product_default_enabled': False,
        'limitations': ['모델 응답/원문/회사 상세는 보고서에 포함하지 않음',
                       'graph는 조항 수준 판정이므로 legacy 공고 전체 결과와 직접 비교 불가',
                       '변경공고 의미 diff 및 실제 브라우저/Copilot 검증은 별도']}


def emit(report: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 동명 파일을 덮어써 검증 기록을 잃지 않는다. 사용자 자료 접근 범위를 최소화한다.
    with open(destination, 'x', encoding='utf-8', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({key: report.get(key) for key in ('probe_version', 'mode', 'model_calls', 'quality_verdict')}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', type=UUID, required=True)
    parser.add_argument('--notice-number', default='R26BK01684863')
    parser.add_argument('--reference-date', type=date.fromisoformat, required=True)
    parser.add_argument('--live-model', action='store_true')
    parser.add_argument('--runs', type=int, choices=range(2, 11), default=3)
    parser.add_argument('--max-calls', type=int, choices=range(1, 201), default=60)
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument('--model')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('출력 파일이 이미 존재합니다. 새로운 파일명을 사용해 주세요.')
    # 기존 프로젝트 env 로딩 규칙을 재사용하되 경로/자격증명은 출력하지 않는다.
    from apps.api.app.scripts.evaluate_copilot_e2_routing import load_local_env, repository_root
    load_local_env(repository_root())
    if args.live_model and not os.getenv('OPENAI_API_KEY'):
        print('NOT_RUN: OPENAI_API_KEY가 실행 환경에 설정되어 있지 않습니다.')
        return 2
    from sqlalchemy import create_engine
    from apps.api.app.config import get_settings
    engine = None
    try:
        engine = create_engine(get_settings().sqlalchemy_database_url)
        captured = capture_case(engine, args.case_id, args.notice_number)
    except Exception as error:
        print('NOT_RUN: '+(str(error) if isinstance(error, ProbeError) else 'READ_ONLY_CAPTURE_FAILED'))
        return 2
    finally:
        if engine is not None:
            engine.dispose()
    if args.live_model:
        from openai import OpenAI
        from apps.api.app.ai.providers.openai import OpenAIStructuredExtractor
        delegate = OpenAIStructuredExtractor(model=args.model,
            client_factory=lambda key: OpenAI(api_key=key, timeout=90.0, max_retries=0))
        try:
            report = measure(captured, reference_date=args.reference_date,
                extractor=BudgetedExtractor(delegate, args.max_calls), runs=args.runs, strategies=tuple(args.strategies))
        except ProbeError as error:
            print('NOT_RUN: '+str(error)); return 2
        report['mode'] = 'LIVE_MODEL'
    else:
        report = {'probe_version': PROBE_VERSION, 'mode': 'CAPTURE_ONLY', 'manifest': captured.manifest(),
                  'model_calls': 0, 'db_writes': False, 'quality_verdict': 'NOT_ESTABLISHED'}
    try:
        report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        report['commit'] = None
    emit(report, args.output)
    return 3 if any(row['execution'] == 'ERROR' for row in report.get('rows', [])) else 0


if __name__ == '__main__':
    raise SystemExit(main())
