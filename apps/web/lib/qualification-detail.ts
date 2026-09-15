/** 참가자격 상세 전용 읽기 계약. 상태 API가 선택한 ID만 사용한다.
 * 모델 호출/저장은 write 포트에서만 수행하며 GET 실패를 미검토로 바꾸지 않는다.
 * 다른 화면의 기존 case-workspace나 Copilot 결과 선택 정책은 수정하지 않는다.
 */
import type { BidNoticeVersion, PreflightCase } from './api';
import type {
  ExtractionStrategy, QualificationAnalysisRun, QualificationAnalysisSummary, QualificationJudgmentRun,
  QualificationJudgmentSummary, QualificationQuestion,
} from './qualification-api';
import { parseQualificationState, type QualificationState } from './qualification-state';

export class QualificationDetailError extends Error {
  constructor(public readonly code: string, message: string) { super(message); }
}
function invalid(): never {
  throw new QualificationDetailError('QUALIFICATION_DETAIL_INVALID', '분석·판정·근거의 기준이 일치하지 않습니다. 상태를 다시 조회해 주세요.');
}
function changed(): never {
  throw new QualificationDetailError('QUALIFICATION_DETAIL_CHANGED', '조회 중 검토 기준이 바뀌었습니다. 상태를 다시 조회해 주세요.');
}
function checkActive(signal?: AbortSignal) {
  if (signal?.aborted) throw new QualificationDetailError('DETAIL_ABORTED', '이전 화면의 조회를 중단했습니다.');
}
function unique(values: string[]) {
  return values.every(v => typeof v === 'string' && v.trim().length > 0) && new Set(values).size === values.length;
}
function comparable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(comparable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, comparable(item)]));
  return value;
}
function caseBasis(item: PreflightCase) {
  return [item.id, item.notice_id, item.company_id, item.current_version_number, item.baseline_version_number];
}
export interface QualificationDetailReads {
  getCase(id: string): Promise<PreflightCase>;
  getVersions(noticeId: string): Promise<BidNoticeVersion[]>;
  getState(caseId: string, signal?: AbortSignal): Promise<QualificationState>;
  getAnalysis(id: string): Promise<QualificationAnalysisRun>;
  getJudgment(id: string): Promise<QualificationJudgmentRun>;
  listAnalyses(noticeId: string, version: number): Promise<QualificationAnalysisSummary[]>;
  listJudgments(caseId: string): Promise<QualificationJudgmentSummary[]>;
  getQuestions(caseId: string, judgmentId: string): Promise<QualificationQuestion[]>;
}
export type QualificationDetail = {
  caseItem: PreflightCase;
  versions: BidNoticeVersion[];
  currentVersion: BidNoticeVersion;
  state: QualificationState;
  analysis: QualificationAnalysisRun | null;
  judgment: QualificationJudgmentRun | null;
  questions: QualificationQuestion[];
  baseline: { version: BidNoticeVersion | null; analysis: QualificationAnalysisRun | null; judgment: QualificationJudgmentRun | null };
  warnings: string[];
};

export function validateAnalysis(analysis: QualificationAnalysisRun, id: string, noticeId: string, version: BidNoticeVersion) {
  if (!analysis || typeof id !== 'string' || !id.trim() || analysis.id !== id || analysis.notice_id !== noticeId || analysis.notice_version_id !== version.id
      || analysis.version_number !== version.version_number || !['SUCCEEDED', 'PARTIAL', 'FAILED'].includes(analysis.status)
      || analysis.contract_version !== 'ai-analysis-v0.2' || analysis.analysis_kind !== 'QUALIFICATION_REQUIREMENTS'
      || !Array.isArray(analysis.requirements) || !Array.isArray(analysis.evidence)
      || !Array.isArray(analysis.diagnostics) || !Array.isArray(analysis.dropped_requirements)
      || (analysis.requirement_count !== undefined && analysis.requirement_count !== analysis.requirements.length)
      || (analysis.evidence_count !== undefined && analysis.evidence_count !== analysis.evidence.length)) invalid();
  if (analysis.extraction_strategy != null && !['legacy', 'review_v1'].includes(analysis.extraction_strategy)) invalid();
  if (analysis.execution_basis != null && (analysis.execution_basis.version !== 'qualification-extraction-basis-v1'
      || analysis.execution_basis.strategy !== analysis.extraction_strategy
      || !/^[a-f0-9]{64}$/.test(analysis.execution_basis.input_sha256)
      || !/^[a-f0-9]{64}$/.test(analysis.execution_basis.source_sha256))) invalid();
  if (!unique(analysis.requirements.map(x => x.requirement_key)) || !unique(analysis.evidence.map(x => x.evidence_key))) invalid();
  const evidence = new Set(analysis.evidence.map(x => x.evidence_key));
  const documents = new Set(version.documents.map(x => x.id));
  for (const item of analysis.evidence) {
    const original = item as typeof item & { notice_version_id?: string | null };
    if (typeof item.quote !== 'string' || !documents.has(item.document_id)
        || (original.notice_version_id !== undefined && original.notice_version_id !== version.id)) invalid();
  }
  for (const req of analysis.requirements) {
    if (req.notice_version_id !== version.id || typeof req.raw !== 'string' || !Array.isArray(req.evidence_keys)
        || req.evidence_keys.some(key => !evidence.has(key))) invalid();
  }
  if (analysis.status === 'FAILED' && (analysis.requirements.length || analysis.evidence.length)) invalid();
}
export function validateJudgment(run: QualificationJudgmentRun, id: string, caseItem: PreflightCase,
                                 analysis: QualificationAnalysisRun, ruleVersion: string) {
  if (!run || typeof id !== 'string' || !id.trim() || run.id !== id || run.preflight_case_id !== caseItem.id || run.company_id !== caseItem.company_id
      || run.notice_version_id !== analysis.notice_version_id || run.analysis_run_id !== analysis.id
      || run.analysis_status !== analysis.status || run.rule_version !== ruleVersion
      || !['eligible', 'ineligible', 'insufficient_data'].includes(run.overall_status)
      || typeof run.reference_date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(run.reference_date)
      || !Number.isFinite(Date.parse(run.reference_date)) || new Date(run.reference_date).toISOString().slice(0, 10) !== run.reference_date
      || !Array.isArray(run.judgments) || !unique(run.judgments.map(x => x.requirement_key))) invalid();
  const requirements = new Map(analysis.requirements.map(x => [x.requirement_key, x]));
  if (requirements.size !== run.judgments.length) invalid();
  for (const item of run.judgments) {
    const req = requirements.get(item.requirement_key);
    if (!req || !['SATISFIED', 'UNSATISFIED', 'UNKNOWN'].includes(item.status)
        || !['PROFILE', 'USER_ANSWER', 'NONE'].includes(item.basis_type)
        || !Array.isArray(item.requirement_evidence_keys)
        || item.requirement_evidence_keys.some(key => !req.evidence_keys.includes(key))) invalid();
  }
  // 기존 TS 선언에 없는 스냅샷을 현재 회사 프로필로 대체하지 않는다.
  const snapshot = (run as QualificationJudgmentRun & { profile_snapshot?: Record<string, unknown> }).profile_snapshot;
  if (snapshot !== undefined && (!snapshot || snapshot.company_id !== caseItem.company_id)) invalid();
}
const newest = <T extends { id: string; created_at: string }>(items: T[]): T | undefined => {
  if (!unique(items.map(x => x.id)) || items.some(x => !Number.isFinite(Date.parse(x.created_at)))) invalid();
  return [...items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id.localeCompare(a.id))[0];
};

export async function loadQualificationDetail(caseId: string, reads: QualificationDetailReads,
                                               signal?: AbortSignal): Promise<QualificationDetail> {
  checkActive(signal);
  const caseItem = await reads.getCase(caseId);
  if (caseItem.id !== caseId) invalid();
  checkActive(signal);
  const [versions, beforeRaw] = await Promise.all([reads.getVersions(caseItem.notice_id), reads.getState(caseId, signal)]);
  checkActive(signal);
  const state = structuredClone(parseQualificationState(beforeRaw, caseId));
  const current = versions.filter(x => x.version_number === caseItem.current_version_number);
  if (current.length !== 1 || state.scope.company_id !== caseItem.company_id
      || state.scope.notice_id !== caseItem.notice_id || state.scope.notice_version_id !== current[0].id) invalid();
  if (state.lookup_state !== 'OK') throw new QualificationDetailError('QUALIFICATION_STATE_UNAVAILABLE', '상태를 불러오지 못했습니다. 다시 조회해 주세요.');
  const currentVersion = current[0];
  const selected = state.selected_judgment_run_id;
  if (selected && (state.judgment_state !== 'AVAILABLE' || state.profile_check !== 'MATCH'
      || !['RESULT_AVAILABLE', 'ANALYSIS_INCOMPLETE'].includes(state.display_state)
      || !['CURRENT', 'CHECKS_INCOMPLETE'].includes(state.freshness_state))) invalid();
  const analysis = state.analysis_run_id && !['DATA_INVALID', 'ANALYSIS_RUNNING'].includes(state.display_state)
    ? await reads.getAnalysis(state.analysis_run_id) : null;
  checkActive(signal);
  if (analysis) {
    validateAnalysis(analysis, state.analysis_run_id!, caseItem.notice_id, currentVersion);
    if (analysis.status !== state.execution_state) changed();
  }
  const judgment = selected ? await reads.getJudgment(selected) : null;
  checkActive(signal);
  if (judgment) {
    if (!analysis) invalid();
    validateJudgment(judgment, selected!, caseItem, analysis, state.scope.rule_version);
    if (judgment.overall_status !== state.stored_overall_status || judgment.reference_date !== state.stored_reference_date) invalid();
  }
  const warnings: string[] = [];
  let questions: QualificationQuestion[] = [];
  if (judgment) {
    try {
      const rows = await reads.getQuestions(caseId, judgment.id);
      if (!Array.isArray(rows) || !unique(rows.map(x => x.requirement_key))
          || rows.some(x => typeof x.askable !== 'boolean' || !analysis!.requirements.some(r => r.requirement_key === x.requirement_key))) invalid();
      questions = rows;
    } catch {
      // 후속 질문 조회 실패가 이미 저장된 판정 실패/미검토라는 뜻은 아니다.
      warnings.push('추가 질문을 불러오지 못했습니다. 저장 판정은 유지하며, 화면 다시 조회로 질문을 확인해 주세요.');
    }
  }
  checkActive(signal);
  const baseline: QualificationDetail['baseline'] = { version: null, analysis: null, judgment: null };
  const baselineNumber = caseItem.baseline_version_number;
  if (baselineNumber !== null && baselineNumber !== caseItem.current_version_number) {
    const candidates = versions.filter(x => x.version_number === baselineNumber);
    if (candidates.length !== 1 || baselineNumber >= caseItem.current_version_number) invalid();
    baseline.version = candidates[0];
    try {
      const summary = newest(await reads.listAnalyses(caseItem.notice_id, baselineNumber));
      checkActive(signal);
      if (summary) {
        if (summary.notice_version_id !== baseline.version.id || summary.version_number !== baselineNumber) invalid();
        const detail = await reads.getAnalysis(summary.id);
        validateAnalysis(detail, summary.id, caseItem.notice_id, baseline.version);
        if (detail.status !== summary.status) changed();
        baseline.analysis = detail;
        if (detail.status === 'SUCCEEDED') {
          const rows = await reads.listJudgments(caseId);
          const source = newest(rows.filter(x => x.analysis_run_id === detail.id && x.company_id === caseItem.company_id
            && x.notice_version_id === baseline.version!.id && x.rule_version === state.scope.rule_version));
          if (source) {
            const run = await reads.getJudgment(source.id);
            validateJudgment(run, source.id, caseItem, detail, state.scope.rule_version);
            baseline.judgment = run;
          }
        }
      }
      const latest = newest(await reads.listAnalyses(caseItem.notice_id, baselineNumber));
      if ((latest?.id ?? null) !== (baseline.analysis?.id ?? null)) changed();
      if (latest && baseline.analysis && latest.status !== baseline.analysis.status) changed();
    } catch {
      baseline.analysis = null;
      baseline.judgment = null;
      warnings.push('기준 차수의 분석·판정을 확인하지 못했습니다. 변경 재검증은 현재 결과와 분리해 다시 확인해야 합니다.');
    }
  }
  checkActive(signal);
  const [afterRaw, afterCase] = await Promise.all([reads.getState(caseId, signal), reads.getCase(caseId)]);
  checkActive(signal);
  const after = parseQualificationState(afterRaw, caseId);
  // 화면 조회 동안 기준이 달라지면 서로 다른 응답을 조합해 보여주지 않는다.
  // 이 비교는 쓰기 잠금/CAS나 서버 권한 검사를 대체하지 않는다.
  if (JSON.stringify(comparable(state)) !== JSON.stringify(comparable(after))
      || JSON.stringify(caseBasis(caseItem)) !== JSON.stringify(caseBasis(afterCase))) changed();
  return { caseItem, versions, currentVersion, state: after, analysis, judgment, questions, baseline, warnings };
}

export function canRejudge(detail: QualificationDetail): boolean {
  return Boolean(detail.caseItem.company_id && detail.analysis?.requirements.length
    && detail.analysis.status !== 'FAILED' && !['DATA_INVALID', 'ANALYSIS_RUNNING'].includes(detail.state.display_state));
}
export function canRevalidateDetail(detail: QualificationDetail): boolean {
  return Boolean(detail.judgment && detail.state.display_state === 'RESULT_AVAILABLE'
    && detail.analysis?.status === 'SUCCEEDED' && detail.baseline.analysis?.status === 'SUCCEEDED'
    && detail.baseline.judgment && detail.baseline.version
    && detail.baseline.version.id !== detail.currentVersion.id);
}
export type ReviewMode = 'start' | 'reanalyze' | 'rejudge' | 'baseline';
export type ReviewStage = 'checking' | 'analysis' | 'judgment' | 'refresh';
export type WriteReceipt = { kind: 'analysis' | 'judgment'; id: string; version_number: number };
export interface QualificationDetailWrites {
  load(caseId: string, signal?: AbortSignal): Promise<QualificationDetail>;
  analyze(noticeId: string, version: number, strategy?: ExtractionStrategy): Promise<QualificationAnalysisRun>;
  judge(caseId: string, analysisId: string): Promise<QualificationJudgmentRun>;
}
export type ReviewOutcome = {
  status: 'COMPLETE' | 'REFRESH_FAILED' | 'WRITE_UNCONFIRMED' | 'ABANDONED';
  detail: QualificationDetail | null;
  receipts: WriteReceipt[];
  message: string;
};
/** 명시적인 사용자 동작만 POST를 시작한다. 저장 후 GET 실패를 POST 재시도로 바꾸지 않는다. */
export async function executeQualificationReview(detail: QualificationDetail, mode: ReviewMode,
  writes: QualificationDetailWrites, onStage: (stage: ReviewStage) => void = () => {}, signal?: AbortSignal,
  requestedStrategy?: ExtractionStrategy): Promise<ReviewOutcome> {
  if (!['start', 'reanalyze', 'rejudge', 'baseline'].includes(mode)) invalid();
  if (requestedStrategy !== undefined && !['legacy', 'review_v1'].includes(requestedStrategy)) invalid();
  const receipts: WriteReceipt[] = [];
  checkActive(signal);
  onStage('checking');
  const before = await writes.load(detail.caseItem.id, signal);
  checkActive(signal);
  if (JSON.stringify(caseBasis(before.caseItem)) !== JSON.stringify(caseBasis(detail.caseItem))) changed();
  if (!before.caseItem.company_id || before.state.execution_state === 'RUNNING') invalid();
  const version = mode === 'baseline' ? before.baseline.version : before.currentVersion;
  if (!version) invalid();
  if (mode === 'rejudge' && (!canRejudge(before) || detail.state.analysis_run_id !== before.state.analysis_run_id)) changed();
  let analysis = mode === 'baseline' ? before.baseline.analysis : before.analysis;
  // 명시적으로 선택한 새 경로를 이전 경로/출처 미확인 분석으로 대체하지 않는다.
  const reuse = analysis && analysis.status === 'SUCCEEDED' && analysis.requirements.length > 0
    && (requestedStrategy === undefined || analysis.extraction_strategy === requestedStrategy);
  let posted = false;
  try {
    if (mode === 'reanalyze' || (mode !== 'rejudge' && !reuse)) {
      checkActive(signal);
      onStage('analysis'); posted = true;
      analysis = await writes.analyze(before.caseItem.notice_id, version.version_number, requestedStrategy);
      validateAnalysis(analysis, analysis?.id, before.caseItem.notice_id, version);
      if (requestedStrategy !== undefined && analysis.extraction_strategy !== requestedStrategy) {
        throw new QualificationDetailError('EXTRACTION_STRATEGY_MISMATCH', '요청한 분석 경로와 저장 응답이 다릅니다. 판정을 실행하지 않았습니다.');
      }
      receipts.push({ kind: 'analysis', id: analysis.id, version_number: version.version_number });
      checkActive(signal);
    }
    if (!analysis || analysis.status === 'FAILED' || !analysis.requirements.length) {
      // 실패/0건 분석을 판정으로 보내지 않고 저장 상태만 다시 조회한다.
      onStage('refresh');
      try {
        const refreshed = await writes.load(before.caseItem.id, signal);
        checkActive(signal);
        return { status: 'COMPLETE', detail: refreshed, receipts,
          message: '분석 처리는 끝났지만 판정 가능한 요건을 확보하지 못했습니다.' };
      } catch {
        return { status: signal?.aborted ? 'ABANDONED' : 'REFRESH_FAILED', detail: null, receipts,
          message: '분석 응답은 확인했지만 후속 상태 조회에 실패했습니다. 화면 상태만 다시 조회해 주세요.' };
      }
    }
    checkActive(signal);
    onStage('judgment'); posted = true;
    const judgment = await writes.judge(before.caseItem.id, analysis.id);
    validateJudgment(judgment, judgment?.id, before.caseItem, analysis, before.state.scope.rule_version);
    receipts.push({ kind: 'judgment', id: judgment.id, version_number: version.version_number });
    checkActive(signal);
  } catch (error) {
    if (signal?.aborted) return { status: 'ABANDONED', detail: null, receipts, message: '이전 화면 작업을 중단했습니다. 전송된 요청은 서버에서 완료될 수 있습니다.' };
    if (!posted) throw error;
    // 응답이 끊긴 POST는 성공/실패를 단정할 수 없다. 재전송하지 않고 현재 상태만 조회한다.
    let refreshed: QualificationDetail | null = null;
    try { refreshed = await writes.load(before.caseItem.id, signal); } catch { /* 화면에 명시적인 재조회 동작을 남긴다. */ }
    return { status: signal?.aborted ? 'ABANDONED' : 'WRITE_UNCONFIRMED', detail: refreshed, receipts,
      message: refreshed
        ? '요청 결과를 확정하지 못했습니다. 현재 상태를 조회했으며, 쓰기 요청은 자동으로 반복하지 않았습니다.'
        : '요청 결과와 후속 상태를 확인하지 못했습니다. 쓰기 요청은 자동으로 반복하지 않았습니다. 상태만 다시 조회해 주세요.' };
  }
  onStage('refresh');
  try {
    const refreshed = await writes.load(before.caseItem.id, signal);
    checkActive(signal);
    const last = [...receipts].reverse().find(x => x.kind === 'judgment');
    const selected = mode === 'baseline' ? refreshed.baseline.judgment?.id : refreshed.state.selected_judgment_run_id;
    return { status: 'COMPLETE', detail: refreshed, receipts,
      message: selected === last?.id
        ? '판정 저장 후 상태와 근거를 다시 조회했습니다. 분석 완전성과 판정 기준은 아래에서 별도로 확인해 주세요.'
        : '판정은 저장됐지만 현재 선택된 결과가 달라졌습니다. 아래에는 서버가 선택한 현재 상태를 표시합니다.' };
  } catch {
    return { status: signal?.aborted ? 'ABANDONED' : 'REFRESH_FAILED', detail: null, receipts,
      message: '판정 저장은 확인했지만 후속 상태 조회에 실패했습니다. 다시 실행하지 말고 화면 상태만 다시 조회해 주세요.' };
  }
}
/** 새 조회가 시작되거나 화면이 바뀌면 이전 비동기 응답을 반영하지 않는다. */
export function createDetailRequestGate() {
  let version = 0;
  let controller: AbortController | null = null;
  return {
    begin() {
      controller?.abort(); controller = new AbortController();
      const mine = ++version, active = controller;
      return { signal: active.signal, isCurrent: () => mine === version && !active.signal.aborted };
    },
    cancel() { ++version; controller?.abort(); controller = null; },
  };
}
