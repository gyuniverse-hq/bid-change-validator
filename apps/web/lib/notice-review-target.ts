import { apiFetch, getNoticeVersions, getPreflightCase, type PreflightCase } from '@/lib/api';
import { createPreflightCaseWithCompany } from '@/lib/qualification-api';

export type ReviewTarget = { noticeId: string; bidNoticeNo: string; versionNumber: number; companyId: string; caseId?: string | null };
/** 명시적 버튼에서만 호출한다. 읽는 동안 차수가 바뀌면 다른 차수를 몰래 생성하지 않는다. */
export async function openReviewTarget(target: ReviewTarget): Promise<string> {
  if (!target.companyId || !target.noticeId) throw new Error('회사와 공고를 먼저 선택해 주세요.');
  const versions = await getNoticeVersions(target.noticeId);
  const current = versions.filter((item) => item.is_current);
  if (current.length !== 1 || current[0].version_number !== target.versionNumber) throw new Error('공고 차수가 변경되었거나 확인되지 않습니다. 목록을 새로 조회해 주세요.');
  if (target.caseId) {
    const existing = await getPreflightCase(target.caseId);
    if (existing.company_id !== target.companyId || existing.notice_id !== target.noticeId || existing.current_version_number !== target.versionNumber) throw new Error('검토 건의 회사 또는 차수가 일치하지 않습니다. 목록을 새로 조회해 주세요.');
    return existing.id;
  }
  // 전역 상위 100건 대신 이 회사/공고의 검토 건을 모두 확인한다. 조회 실패 시 생성 금지.
  let offset = 0;
  for (let page = 0; page < 100; page += 1) {
    const params = new URLSearchParams({ company_id: target.companyId, notice_id: target.noticeId, limit: '100', offset: String(offset) });
    const response = await apiFetch(`/api/v1/preflight-cases?${params}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('기존 검토 건을 확인하지 못했습니다. 새 검토 건을 만들지 않았습니다.');
    const data = await response.json() as { total: number; items: PreflightCase[] };
    if (!Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0) throw new Error('검토 목록 응답이 올바르지 않습니다.');
    const existing = data.items.find((item) => item.company_id === target.companyId && item.notice_id === target.noticeId && item.current_version_number === target.versionNumber);
    if (existing) return existing.id;
    offset += data.items.length;
    if (offset >= data.total) break;
    if (data.items.length === 0 || page === 99) throw new Error('기존 검토 건 전체를 확인하지 못해 생성을 중단했습니다.');
  }
  const baseline = versions.filter((item) => item.version_number < target.versionNumber)
    .sort((a, b) => b.version_number - a.version_number)[0];
  const created = await createPreflightCaseWithCompany({ notice_id: target.noticeId, company_id: target.companyId,
    current_version_number: target.versionNumber, baseline_version_number: baseline?.version_number,
    title: `${target.bidNoticeNo} 참가자격 검토` });
  return created.id;
}
