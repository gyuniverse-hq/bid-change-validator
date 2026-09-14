/** 상세 조회는 cache:no-store와 하나의 취소 신호를 사용한다. POST를 자동 재시도하지 않는다. */
import { apiFetch, ApiError } from '@/lib/api';
import { runQualificationAnalysis, runQualificationJudgment } from '@/lib/qualification-api';
import { getQualificationState } from '@/lib/qualification-state-api';
import {
  loadQualificationDetail, executeQualificationReview,
  type QualificationDetailReads, type QualificationDetail, type ReviewMode, type ReviewStage,
} from '@/lib/qualification-detail';

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(path, { signal, cache: 'no-store' });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(data?.error?.message ?? '검토 정보를 불러오지 못했습니다.', response.status, data?.error?.code ?? 'HTTP_ERROR');
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
  onStage: (stage: ReviewStage) => void, signal?: AbortSignal) {
  return executeQualificationReview(detail, mode, {
    load: loadCurrentQualificationDetail, analyze: runQualificationAnalysis, judge: runQualificationJudgment,
  }, onStage, signal);
}
