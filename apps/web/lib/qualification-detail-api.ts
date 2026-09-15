/** 상세 조회는 cache:no-store와 하나의 취소 신호를 사용한다. POST를 자동 재시도하지 않는다. */
import { apiFetch, ApiError } from '@/lib/api';
import { runQualificationAnalysis, runQualificationJudgment, type ExtractionStrategy } from '@/lib/qualification-api';
import { getQualificationState } from '@/lib/qualification-state-api';
import {
  loadQualificationDetail, executeQualificationReview,
  type QualificationDetailReads, type QualificationDetail, type ReviewMode, type ReviewStage,
} from '@/lib/qualification-detail';

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(path, { signal, cache: 'no-store' });
  // DOM/Workers의 Response.json 반환 타입이 달라도 수신값은 unknown에서 검사한다.
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const candidate = data && typeof data === 'object' && 'error' in data ? data.error : null;
    const error = candidate && typeof candidate === 'object' ? candidate : null;
    const message = error && 'message' in error && typeof error.message === 'string'
      ? error.message : '검토 정보를 불러오지 못했습니다.';
    const code = error && 'code' in error && typeof error.code === 'string' ? error.code : 'HTTP_ERROR';
    throw new ApiError(message, response.status, code);
  }
  if (data === null) throw new ApiError('검토 정보 응답 형식이 올바르지 않습니다.', response.status, 'INVALID_RESPONSE');
  return data as T;
}
export function detailReadPorts(signal?: AbortSignal): QualificationDetailReads {
  const part = encodeURIComponent;
  return {
    getCase: id => read(`/api/v1/preflight-cases/${part(id)}`, signal),
    getVersions: id => read(`/api/v1/notices/${part(id)}/versions`, signal),
    getState: (id, localSignal) => getQualificationState(id, localSignal ?? signal),
    getAnalysis: id => read(`/api/v1/qualification-analyses/${part(id)}`, signal),
    getJudgment: id => read(`/api/v1/qualification-judgment-runs/${part(id)}`, signal),
    listAnalyses: (id, version) => read(`/api/v1/notices/${part(id)}/versions/${version}/qualification-analyses`, signal),
    listJudgments: id => read(`/api/v1/preflight-cases/${part(id)}/qualification-judgment-runs`, signal),
    getQuestions: (id, run) => read(`/api/v1/preflight-cases/${part(id)}/qualification-questions?${new URLSearchParams({ source_judgment_run_id: run })}`, signal),
  };
}
export function loadCurrentQualificationDetail(caseId: string, signal?: AbortSignal) {
  return loadQualificationDetail(caseId, detailReadPorts(signal), signal);
}
export function runCurrentQualificationReview(detail: QualificationDetail, mode: ReviewMode,
  onStage: (stage: ReviewStage) => void, signal?: AbortSignal, strategy?: ExtractionStrategy) {
  return executeQualificationReview(detail, mode, {
    load: loadCurrentQualificationDetail, analyze: runQualificationAnalysis, judge: runQualificationJudgment,
  }, onStage, signal, strategy);
}

export type AnalysisOptions = {
  contract_version: 'qualification-analysis-options-v1'; default_strategy: 'legacy';
  strategies: { id: ExtractionStrategy; enabled: boolean }[]; graph_product_enabled: false;
};
export async function getAnalysisOptions(signal?: AbortSignal): Promise<AnalysisOptions> {
  const data = await read<AnalysisOptions>('/api/v1/qualification-analysis-options', signal);
  if (data.contract_version !== 'qualification-analysis-options-v1' || data.default_strategy !== 'legacy'
      || data.graph_product_enabled !== false || !Array.isArray(data.strategies)
      || data.strategies.length !== 2 || new Set(data.strategies.map(x => x.id)).size !== 2
      || data.strategies.some(x => !['legacy', 'review_v1'].includes(x.id) || typeof x.enabled !== 'boolean')
      || !data.strategies.some(x => x.id === 'legacy' && x.enabled)) {
    throw new ApiError('사용 가능한 분석 경로를 확인하지 못했습니다.', 0, 'INVALID_ANALYSIS_OPTIONS');
  }
  return data;
}
