import { absoluteApiUrl, ApiError, type PreflightCase } from '@/lib/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(absoluteApiUrl(path), { ...init, headers });
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

export type CompanyProfile = {
  id: string;
  name: string;
  region_code: string | null;
  region_name: string | null;
  company_size: string;
  industries: Array<{ code: string; name: string; verified: boolean }>;
  staff: {
    total_count: number;
    verified: boolean;
    roles: Array<{ role_name: string; headcount: number; verified: boolean }>;
  } | null;
  performances: Array<{ id: string; name: string; amount: number; verified: boolean }>;
  certifications: Array<{ id: string; name: string; verified: boolean }>;
};

export type CanonicalRequirement = {
  requirement_key: string;
  requirement_group_key: string | null;
  group_operator: 'ALL_OF' | 'ANY_OF' | null;
  notice_version_id: string;
  type: string;
  operator: string | null;
  value: string | number | null;
  unit: string | null;
  period_months: number | null;
  scope: Record<string, unknown>;
  required: boolean;
  raw: string;
  evidence_keys: string[];
};

export type QualificationAnalysisSummary = {
  id: string;
  notice_version_id: string;
  version_number: number;
  contract_version: string;
  status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED';
  requirement_count: number;
  evidence_count: number;
  created_at: string;
};

export type QualificationAnalysisRun = QualificationAnalysisSummary & {
  notice_id: string;
  analysis_kind: string;
  target_chunk_ids: string[];
  diagnostics: Array<{ code: string; severity: string; message: string }>;
  requirements: CanonicalRequirement[];
  evidence: Array<{
    evidence_key: string;
    document_id: string;
    quote: string;
    location: Record<string, unknown>;
  }>;
};

export type QualificationJudgment = {
  judgment_key: string;
  requirement_key: string;
  status: 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN';
  basis_type: 'PROFILE' | 'USER_ANSWER' | 'NONE';
  evidence_held: boolean;
  reason_code: string;
  requires_evidence: boolean;
  requirement_evidence_keys: string[];
};

export type QualificationJudgmentRun = {
  id: string;
  preflight_case_id: string;
  analysis_run_id: string;
  company_id: string;
  notice_version_id: string;
  overall_status: 'eligible' | 'ineligible' | 'insufficient_data';
  rule_version: string;
  reference_date: string;
  analysis_status: string;
  profile_completeness: Record<string, boolean>;
  judgments: QualificationJudgment[];
  created_at: string;
};

export type QualificationJudgmentSummary = {
  id: string;
  analysis_run_id: string;
  company_id: string;
  notice_version_id: string;
  overall_status: 'eligible' | 'ineligible' | 'insufficient_data';
  judgment_count: number;
  unknown_count: number;
  unsatisfied_count: number;
  created_at: string;
};

export type QualificationQuestion = {
  requirement_key: string;
  requirement_type: string;
  question: string;
  raw_requirement: string;
};

export type RequirementChange = {
  change_type: 'UNCHANGED' | 'MODIFIED' | 'ADDED' | 'REMOVED';
  identity: string;
  baseline_key: string | null;
  current_key: string | null;
};

export type QualificationRevalidation = {
  id: string;
  changes: RequirementChange[];
  revalidated_keys: string[];
  result: QualificationJudgmentRun;
};

export function listCompanies() {
  return request<CompanyProfile[]>('/api/v1/companies');
}

export function createPreflightCaseWithCompany(payload: {
  notice_id: string;
  company_id: string;
  baseline_version_number?: number;
  current_version_number: number;
  title: string;
}) {
  return request<PreflightCase>('/api/v1/preflight-cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listQualificationAnalyses(noticeId: string, versionNumber: number) {
  return request<QualificationAnalysisSummary[]>(
    `/api/v1/notices/${noticeId}/versions/${versionNumber}/qualification-analyses`,
  );
}

export function runQualificationAnalysis(noticeId: string, versionNumber: number) {
  return request<{ run: QualificationAnalysisRun }>(
    `/api/v1/notices/${noticeId}/versions/${versionNumber}/qualification-analysis`,
    { method: 'POST' },
  );
}

export function getQualificationAnalysis(runId: string) {
  return request<QualificationAnalysisRun>(`/api/v1/qualification-analyses/${runId}`);
}

export function listQualificationJudgments(caseId: string) {
  return request<QualificationJudgmentSummary[]>(
    `/api/v1/preflight-cases/${caseId}/qualification-judgment-runs`,
  );
}

export function getQualificationJudgment(runId: string) {
  return request<QualificationJudgmentRun>(`/api/v1/qualification-judgment-runs/${runId}`);
}

export function runQualificationJudgment(caseId: string, analysisRunId: string) {
  return request<QualificationJudgmentRun>(`/api/v1/preflight-cases/${caseId}/qualification-judgments`, {
    method: 'POST',
    body: JSON.stringify({ analysis_run_id: analysisRunId }),
  });
}

export function listQualificationQuestions(caseId: string, sourceRunId: string) {
  const search = new URLSearchParams({ source_judgment_run_id: sourceRunId });
  return request<QualificationQuestion[]>(
    `/api/v1/preflight-cases/${caseId}/qualification-questions?${search}`,
  );
}

export function answerQualificationQuestion(
  caseId: string,
  payload: {
    source_judgment_run_id: string;
    requirement_key: string;
    satisfies_requirement: boolean;
    normalized_value?: string;
    evidence_held?: boolean;
  },
) {
  return request<{ result: QualificationJudgmentRun }>(
    `/api/v1/preflight-cases/${caseId}/qualification-answers`,
    {
      method: 'POST',
      body: JSON.stringify({ ...payload, apply_to_profile: false }),
    },
  );
}

export function runQualificationRevalidation(
  caseId: string,
  payload: {
    source_judgment_run_id: string;
    baseline_analysis_run_id?: string;
    current_analysis_run_id?: string;
  },
) {
  return request<QualificationRevalidation>(
    `/api/v1/preflight-cases/${caseId}/qualification-revalidation`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}
