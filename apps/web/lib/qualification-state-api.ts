import { apiFetch, ApiError } from '@/lib/api';
import { catalogSearch, parseNoticeCatalog, parseQualificationState, type CatalogQuery } from '@/lib/qualification-state';

async function read(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await apiFetch(path, { signal, cache: 'no-store' });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const payload = data as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `상태를 불러오지 못했습니다. (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return data;
}
export async function getQualificationState(caseId: string, signal?: AbortSignal) {
  return parseQualificationState(await read(`/api/v1/preflight-cases/${encodeURIComponent(caseId)}/qualification-state`, signal), caseId);
}
export async function getNoticeCatalog(params: CatalogQuery, signal?: AbortSignal) {
  return parseNoticeCatalog(await read(`/api/v1/qualification-notice-catalog?${catalogSearch(params)}`, signal), params);
}
