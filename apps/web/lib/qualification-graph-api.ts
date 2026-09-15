/** 그래프 전용 API. 기존 판정/Copilot API와 섞지 않는다. 쓰기 자동 재시도 없음. */
import { apiFetch, ApiError } from './api';

export type GraphRun = { id: string; notice_id: string; notice_version_id: string; contract_version: string;
  status: string; snapshot_sha256: string; created_at: string; relation_status: string; clause_count: number };
export type GraphList = { case_id: string; baseline_version_id: string | null; current_version_id: string;
  items: GraphRun[]; limit: number; more_may_exist: boolean };
export type GraphSide = { candidate_id: string; quote: string; document_id: string; block_index: number;
  meaning: { status: string; role: string; pending_codes: string[]; graph_sha256: string | null;
    predicates: Array<Record<string, unknown>> } | null };
export type GraphComparison = { contract_version: 'qualification-graph-comparison-v1'; case_id: string;
  baseline_run_id: string; current_run_id: string; comparison_status: 'COMPLETE' | 'REVIEW_REQUIRED';
  same_source_text: boolean; mode: string; relation_change: string; issues: string[]; counts: Record<string, number>;
  changes: Array<{ id: string; change_type: string; alignment: string; reason_code: string | null;
    before: GraphSide | null; after: GraphSide | null }>;
  eligibility_change_asserted: false; db_writes: false; baseline_relations: unknown; current_relations: unknown };
export type GraphJudgment = { id: string; graph_run_id: string; created_at: string;
  result: { case_id: string; company_id: string; reference_date: string; overall_status: string;
    source_complete: boolean; relation_status: string; semantic_accuracy_verified: false;
    node_results: Record<string, string>; clause_results: unknown[] } };

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
async function request(path: string, signal?: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await apiFetch(path, { method: body === undefined ? 'GET' : 'POST', signal, cache: 'no-store',
    ...(body === undefined ? {} : { headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }) });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const err = object(data) && object(data.error) ? data.error : null;
    throw new ApiError(typeof err?.message === 'string' ? err.message : '그래프 요청 결과를 확인하지 못했습니다.', response.status,
      typeof err?.code === 'string' ? err.code : 'GRAPH_REQUEST_FAILED');
  }
  return data;
}
const base = (caseId: string) => `/api/v1/preflight-cases/${encodeURIComponent(caseId)}`;
export async function graphOptions(signal?: AbortSignal) {
  const d = await request('/api/v1/qualification-graph-options', signal);
  if (!object(d) || d.contract_version !== 'qualification-graph-options-v1' || typeof d.enabled !== 'boolean' || d.copilot_connected !== false) throw Error('그래프 옵션 응답이 올바르지 않습니다.');
  return { enabled: d.enabled };
}
export async function graphRuns(caseId: string, signal?: AbortSignal): Promise<GraphList> {
  const d = await request(`${base(caseId)}/qualification-graphs`, signal);
  if (!object(d) || d.case_id !== caseId || !Array.isArray(d.items) || typeof d.current_version_id !== 'string'
    || d.items.some(r => !object(r) || typeof r.id !== 'string' || typeof r.notice_version_id !== 'string'
      || r.contract_version !== 'qualification-document-graph-v1')
    || new Set(d.items.map(r => (r as GraphRun).id)).size !== d.items.length) throw Error('검토 건의 그래프 목록 기준이 맞지 않습니다.');
  return d as GraphList;
}
export async function analyzeGraph(caseId: string, role: 'baseline' | 'current', signal?: AbortSignal): Promise<GraphRun> {
  const d = await request(`${base(caseId)}/qualification-graphs`, signal, {version_role:role});
  if (!object(d) || typeof d.id !== 'string' || d.contract_version !== 'qualification-document-graph-v1') throw Error('그래프 저장 응답을 확인하지 못했습니다. 재실행 전에 목록을 조회해 주세요.');
  return d as GraphRun;
}
export async function judgeGraph(caseId: string, runId: string, referenceDate: string, signal?: AbortSignal): Promise<GraphJudgment> {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(referenceDate)) throw Error('판정 기준일을 지정해 주세요.');
  const d = await request(`${base(caseId)}/qualification-graph-judgments`, signal, {graph_run_id:runId,reference_date:referenceDate});
  if (!object(d) || d.graph_run_id !== runId || !object(d.result) || d.result.case_id !== caseId
    || d.result.reference_date !== referenceDate || d.result.semantic_accuracy_verified !== false) throw Error('판정 응답의 기준을 확인하지 못했습니다.');
  return d as GraphJudgment;
}
export function parseGraphComparison(d: unknown, caseId: string, before: string, after: string): GraphComparison {
  if (!object(d) || d.contract_version !== 'qualification-graph-comparison-v1' || d.case_id !== caseId
    || d.baseline_run_id !== before || d.current_run_id !== after || d.db_writes !== false
    || d.eligibility_change_asserted !== false || !Array.isArray(d.changes) || !Array.isArray(d.issues)
    || !object(d.counts) || !['COMPLETE','REVIEW_REQUIRED'].includes(String(d.comparison_status))) throw Error('변경 비교의 실행 기준이 일치하지 않습니다.');
  const counts: Record<string, number> = {};
  for (const item of d.changes) {
    if (!object(item) || typeof item.id !== 'string' || typeof item.change_type !== 'string'
      || [item.before,item.after].some(s => s !== null && (!object(s) || typeof s.quote !== 'string'))) throw Error('변경 항목의 원문 연결이 올바르지 않습니다.');
    counts[item.change_type] = (counts[item.change_type] ?? 0) + 1;
  }
  if (JSON.stringify(Object.entries(counts).sort()) !== JSON.stringify(Object.entries(d.counts).sort())) throw Error('변경 항목 집계가 일치하지 않습니다.');
  return d as GraphComparison;
}
export async function compareGraphs(caseId: string, before: string, after: string, signal?: AbortSignal) {
  if (!before || !after || before === after) throw Error('서로 다른 분석 실행을 선택해 주세요.');
  const params = new URLSearchParams({baseline_run_id:before,current_run_id:after});
  return parseGraphComparison(await request(`${base(caseId)}/qualification-graphs/compare?${params}`,signal),caseId,before,after);
}
