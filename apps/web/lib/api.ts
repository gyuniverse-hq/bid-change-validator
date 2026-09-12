const configuredApiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
export const API_BASE_URL = configuredApiBase.replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
  ) {
    super(message);
  }
}

export function absoluteApiUrl(path: string) {
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`;
}

/** Share the existing HttpOnly session only with the configured API origin.
 * Does not persist tokens, retry writes, or send credentials to document hosts.
 */
export function apiFetch(path: string, init: RequestInit = {}) {
  const url = absoluteApiUrl(path);
  const base = new URL(API_BASE_URL, typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
  const target = new URL(url, base);
  return fetch(url, { ...init, credentials: target.origin === base.origin ? 'include' : 'omit' });
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { message?: string; code?: string };
    } | null;
    throw new ApiError(
      payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status,
      payload?.error?.code ?? 'HTTP_ERROR',
    );
  }
  return response.json() as Promise<T>;
}

export type NoticeDocument = {
  id: string;
  document_order: number;
  name: string;
  viewer_type: string;
  render_source_url: string;
  text_url: string;
  preview_url: string | null;
  file_size_bytes: number | null;
  extraction_status: string;
  extracted_char_count: number | null;
};

export type ProposalDocument = {
  id: string;
  case_id: string;
  document_order: number;
  role: string;
  name: string;
  viewer_type: string;
  render_source_url: string;
  text_url: string;
  preview_url: string | null;
  file_size_bytes: number;
  extraction_status: string;
  extracted_char_count: number | null;
};

export type ViewableDocument = NoticeDocument | ProposalDocument;

export type BidNoticeVersion = {
  id: string;
  version_number: number;
  bid_notice_order: string;
  is_current: boolean;
  notice_kind: string | null;
  registration_type: string | null;
  is_reannouncement: boolean;
  posted_at: string | null;
  changed_at: string | null;
  bid_started_at: string | null;
  bid_closed_at: string | null;
  opened_at: string | null;
  allocated_budget: number | null;
  estimated_price: number | null;
  contract_method: string | null;
  change_reason: string | null;
  detail_url: string | null;
  collected_at: string;
  documents: NoticeDocument[];
};

export type BidNoticeSummary = {
  id: string;
  bid_notice_no: string;
  title: string;
  business_type: string;
  notice_kind: string | null;
  announcing_institution_code: string | null;
  announcing_institution_name: string | null;
  demanding_institution_code: string | null;
  demanding_institution_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
  current_version: number;
};

export type BidNoticeDetail = BidNoticeSummary & {
  latest: BidNoticeVersion;
};

export type PreflightCase = {
  id: string;
  company_id: string | null;
  notice_id: string;
  bid_notice_no: string;
  notice_title: string;
  title: string;
  status: string;
  baseline_version_number: number | null;
  current_version_number: number;
  documents: ProposalDocument[];
  created_at: string;
  updated_at: string;
};

export type NoticeDocumentText = {
  document_id: string;
  name: string;
  extraction_status: string;
  extractor: string | null;
  char_count: number | null;
  text_sha256: string | null;
  text: string | null;
  blocks: Array<Record<string, unknown>> | null;
};

type ListResponse<T> = {
  total: number;
  limit: number;
  offset: number;
  items: T[];
};

export function listNotices(query = '') {
  const search = new URLSearchParams({ limit: '100' });
  if (query.trim()) search.set('q', query.trim());
  return apiRequest<ListResponse<BidNoticeSummary>>(`/api/v1/notices?${search}`);
}

export function getNotice(noticeId: string) {
  return apiRequest<BidNoticeDetail>(`/api/v1/notices/${noticeId}`);
}

export function getNoticeVersions(noticeId: string) {
  return apiRequest<BidNoticeVersion[]>(`/api/v1/notices/${noticeId}/versions`);
}

export function listPreflightCases() {
  return apiRequest<ListResponse<PreflightCase>>('/api/v1/preflight-cases?limit=100');
}

export function getPreflightCase(caseId: string) {
  return apiRequest<PreflightCase>(`/api/v1/preflight-cases/${caseId}`);
}

export function createPreflightCase(payload: {
  notice_id: string;
  baseline_version_number?: number;
  current_version_number: number;
  title: string;
}) {
  return apiRequest<PreflightCase>('/api/v1/preflight-cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function uploadProposalDocument(caseId: string, file: File) {
  const body = new FormData();
  body.append('role', 'PROPOSAL');
  body.append('file', file);
  return apiRequest<ProposalDocument>(`/api/v1/preflight-cases/${caseId}/documents`, {
    method: 'POST',
    body,
  });
}

export function getDocumentText(textUrl: string) {
  return apiRequest<NoticeDocumentText>(textUrl);
}
