/** 읽은 저장 판정과 현재 사용할 판정을 분리한다. null/오류를 미검토로 만들지 않는다. */
export type OverallStatus = 'eligible' | 'ineligible' | 'insufficient_data';
export type StatusBucket = OverallStatus | 'unreviewed';
export type QualificationState = {
  contract_version: 'qualification-state-v1';
  scope: { case_id: string; notice_id: string; notice_version_id: string; company_id: string | null; rule_version: string };
  lookup_state: 'OK' | 'FAILED'; execution_state: string; coverage_state: string;
  judgment_state: string; freshness_state: string; display_state: string;
  analysis_run_id: string | null; selected_judgment_run_id: string | null;
  observed_judgment_run_id: string | null; stored_overall_status: OverallStatus | null;
  stored_reference_date: string | null; requested_reference_date: string | null;
  profile_check: string; reference_date_check: string; answer_basis_check: string;
  reasons: string[]; unknown_reasons: string[]; full_notice_eligibility_asserted: false;
  state_sha256: string;
};
export type StateView = { label: string; description: string; tone: 'neutral' | 'success' | 'warning' | 'danger'; bucket: StatusBucket; warnings: string[] };
const LABELS: Record<OverallStatus, string> = { eligible: '응찰 가능', ineligible: '자격 미달', insufficient_data: '확인 필요' };
const WARNINGS: Record<string, string> = {
  PROFILE_CHANGED: '회사 정보가 변경되어 재판정이 필요합니다.',
  REFERENCE_DATE_CHANGED: '판정 기준일이 변경되었습니다.',
  ANALYSIS_CHANGED: '새 분석을 기준으로 다시 판정해야 합니다.',
  RULE_VERSION_CHANGED: '판정 규칙이 변경되었습니다.',
  REFERENCE_DATE_NOT_REQUESTED: '표시된 저장 기준일의 결과입니다. 현재 날짜의 판정으로 해석하지 마세요.',
  ANSWER_FRESHNESS_UNVERIFIED: '사용자 답변의 최신성은 확인되지 않았습니다.',
  ANALYSIS_COMPLETENESS_UNVERIFIED: '전체 요건을 빠짐없이 분석했는지는 확인되지 않았습니다.',
  ANALYSIS_INCOMPLETE: '판정에 반영되지 않은 조건이 있을 수 있습니다.',
};
const DISPLAY: Record<string, [string, string]> = {
  UNREVIEWED: ['미검토', '현재 검토 건의 공고 분석이 필요합니다.'],
  PROFILE_REQUIRED: ['회사 정보 필요', '회사 프로필을 연결한 뒤 판정할 수 있습니다.'],
  JUDGMENT_REQUIRED: ['회사 판정 필요', '공고 분석은 있지만 현재 회사 기준의 저장 판정이 없습니다.'],
  REJUDGMENT_REQUIRED: ['재판정 필요', '기존 결과의 기준이 바뀌었습니다. 과거 결과를 현재 판정으로 사용하지 않습니다.'],
  ANALYSIS_RUNNING: ['분석 중', '분석이 끝나기 전에는 과거 결과를 현재 판정으로 표시하지 않습니다.'],
  ANALYSIS_FAILED: ['분석 실패', '최신 공고 분석이 실패했습니다. 다시 분석해야 합니다.'],
  ANALYSIS_INCOMPLETE: ['분석 확인 필요', '분석되지 않았거나 해석되지 않은 조건을 확인해야 합니다.'],
  DATA_INVALID: ['데이터 연결 확인 필요', '분석·판정·근거 연결에 확인이 필요합니다.'],
  LOAD_FAILED: ['상태 조회 실패', '서버에서 상태를 확인하지 못했습니다. 미검토를 뜻하지 않습니다.'],
};
export function presentQualificationState(state: QualificationState): StateView {
  const warnings = [...new Set(state.reasons.map((reason) => WARNINGS[reason]).filter((v): v is string => Boolean(v)))];
  if (state.lookup_state === 'OK' && state.display_state === 'RESULT_AVAILABLE' && state.selected_judgment_run_id && state.stored_overall_status) {
    const status = state.stored_overall_status;
    return { label: `저장 판정: ${LABELS[status]}`, description: '선택된 분석·회사·규칙 기준으로 저장된 판정입니다.',
      tone: status === 'eligible' ? 'success' : status === 'ineligible' ? 'danger' : 'warning', bucket: status, warnings };
  }
  const code = state.lookup_state === 'FAILED' ? 'LOAD_FAILED' : state.display_state;
  const copy = DISPLAY[code] ?? ['상태 확인 필요', '지원하지 않는 상태 응답입니다. 새 판정을 확정하지 않습니다.'];
  return { label: copy[0], description: copy[1], tone: code === 'UNREVIEWED' ? 'neutral' : 'warning',
    bucket: code === 'UNREVIEWED' ? 'unreviewed' : 'insufficient_data', warnings };
}
export function historicalLabel(state: QualificationState): string | null {
  if (!state.stored_overall_status || !state.observed_judgment_run_id || state.selected_judgment_run_id) return null;
  return `이전 저장 결과: ${LABELS[state.stored_overall_status]} (현재 판정으로 선택되지 않음)`;
}
export const STATE_TONE_CLASS: Record<StateView['tone'], string> = {
  neutral: 'border-slate-200 bg-slate-50 text-slate-700', success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800', danger: 'border-rose-200 bg-rose-50 text-rose-800',
};
/** API 데이터를 수신 경계에서 검사한다. 알 수 없는/불완전한 응답을 eligible로 표시하지 않는다. */
export function parseQualificationState(input: unknown, expectedCaseId?: string): QualificationState {
  if (!input || typeof input !== 'object') throw new Error('판정 상태 응답 형식이 올바르지 않습니다.');
  const s = input as Record<string, unknown>;
  const scope = s.scope as Record<string, unknown> | undefined;
  const identifiers = ['case_id', 'notice_id', 'notice_version_id', 'rule_version'];
  if (s.contract_version !== 'qualification-state-v1' || !scope || identifiers.some((key) => typeof scope[key] !== 'string' || !scope[key])
      || (scope.company_id !== null && typeof scope.company_id !== 'string')
      || (expectedCaseId !== undefined && scope.case_id !== expectedCaseId)
      || !['OK', 'FAILED'].includes(String(s.lookup_state)) || s.full_notice_eligibility_asserted !== false
      || typeof s.state_sha256 !== 'string' || !s.state_sha256
      || ['execution_state', 'coverage_state', 'judgment_state', 'freshness_state', 'display_state', 'profile_check', 'reference_date_check', 'answer_basis_check'].some((key) => typeof s[key] !== 'string')
      || ['reasons', 'unknown_reasons'].some((key) => !Array.isArray(s[key]) || (s[key] as unknown[]).some((item) => typeof item !== 'string'))
      || ['analysis_run_id', 'selected_judgment_run_id', 'observed_judgment_run_id', 'stored_reference_date', 'requested_reference_date'].some((key) => s[key] !== null && (typeof s[key] !== 'string' || !s[key]))
      || (s.stored_overall_status !== null && !['eligible', 'ineligible', 'insufficient_data'].includes(String(s.stored_overall_status)))
      || (s.selected_judgment_run_id !== null && (!s.analysis_run_id || !s.stored_overall_status || s.selected_judgment_run_id !== s.observed_judgment_run_id))) {
    throw new Error('판정 상태의 기준 또는 응답 형식이 일치하지 않습니다.');
  }
  return input as QualificationState;
}
export type CatalogNotice = {
  id: string; bid_notice_no: string; title: string; business_type: string; notice_kind: string | null;
  institution_name: string | null; current_version: number; notice_version_id: string;
  case_id: string | null; state: QualificationState | null; status_bucket: StatusBucket;
  review_basis: 'STORED_JUDGMENT' | 'NO_CURRENT_JUDGMENT';
};
export type NoticeCatalog = {
  contract_version: 'qualification-catalog-v1'; company_id: string | null; query: string;
  business_type: string | null; status_filter: StatusBucket | null; query_total: number; scope_total: number;
  total: number; business_counts: Record<string, number>; status_counts: Record<StatusBucket, number>;
  limit: number; offset: number; items: CatalogNotice[]; scope_sha256: string; full_notice_eligibility_asserted: false;
};
export type CatalogQuery = { companyId?: string; query?: string; businessType?: string; status?: StatusBucket; limit?: number; offset?: number };
export function catalogSearch(params: CatalogQuery): string {
  const search = new URLSearchParams({ limit: String(params.limit ?? 20), offset: String(params.offset ?? 0) });
  if (params.companyId) search.set('company_id', params.companyId);
  if (params.query?.trim()) search.set('q', params.query.trim());
  if (params.businessType) search.set('business_type', params.businessType);
  if (params.status) search.set('status', params.status);
  return search.toString();
}
export function parseNoticeCatalog(input: unknown, params: CatalogQuery): NoticeCatalog {
  if (!input || typeof input !== 'object') throw new Error('공고 목록 응답을 확인해야 합니다.');
  const data = input as NoticeCatalog;
  const numberKeys = ['query_total', 'scope_total', 'total', 'limit', 'offset'] as const;
  if (data.contract_version !== 'qualification-catalog-v1' || data.company_id !== (params.companyId ?? null)
      || data.query !== (params.query?.trim() ?? '') || data.business_type !== (params.businessType ?? null)
      || data.status_filter !== (params.status ?? null) || data.limit !== (params.limit ?? 20) || data.offset !== (params.offset ?? 0)
      || numberKeys.some((key) => !Number.isInteger(data[key]) || data[key] < 0)
      || !Array.isArray(data.items) || data.items.length > data.limit || !data.status_counts || !data.business_counts
      || data.full_notice_eligibility_asserted !== false || typeof data.scope_sha256 !== 'string'
      || Object.values(data.business_counts).some((value) => !Number.isInteger(value) || value < 0)
      || ['eligible', 'insufficient_data', 'ineligible', 'unreviewed'].some((key) => !Number.isInteger(data.status_counts[key as StatusBucket]) || data.status_counts[key as StatusBucket] < 0)
      || Object.values(data.status_counts).reduce((a, b) => a + b, 0) !== data.scope_total
      || Object.values(data.business_counts).reduce((a, b) => a + b, 0) !== data.query_total
      || data.total !== (params.status ? data.status_counts[params.status] : data.scope_total)
      || new Set(data.items.map((item) => item.id)).size !== data.items.length) throw new Error('공고 목록의 검색 기준 또는 집계가 일치하지 않습니다.');
  for (const item of data.items) {
    if (typeof item.id !== 'string' || !item.id || typeof item.title !== 'string' || typeof item.bid_notice_no !== 'string'
        || !Number.isInteger(item.current_version) || item.current_version < 1 || typeof item.notice_version_id !== 'string'
        || (params.businessType && item.business_type !== params.businessType)) throw new Error('공고 항목의 기준이 올바르지 않습니다.');
    const state = item.state === null ? null : parseQualificationState(item.state, item.case_id ?? undefined);
    if ((state && (state.scope.company_id !== data.company_id || state.scope.notice_id !== item.id || state.scope.notice_version_id !== item.notice_version_id))
        || (item.case_id !== null && !state) || (state && item.case_id === null)
        || item.status_bucket !== (state ? presentQualificationState(state).bucket : 'unreviewed')
        || (params.status && item.status_bucket !== params.status)) throw new Error('공고와 판정 상태의 연결이 일치하지 않습니다.');
  }
  return data;
}
