'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { loadCaseWorkspace, type CaseWorkspace } from '@/lib/case-workspace';
import type { CanonicalRequirement } from '@/lib/qualification-api';

function companyValue(requirement: CanonicalRequirement, workspace: CaseWorkspace) {
  const company = workspace.company;
  if (!company) return '프로필에 없음';
  switch (requirement.type) {
    case 'PERFORMANCE_AMOUNT': {
      const total = company.performances.reduce((sum, item) => sum + item.amount, 0);
      return company.performances.length ? `${company.performances.length}건 · 합계 ${(total / 100_000_000).toFixed(1)}억` : '프로필에 없음';
    }
    case 'PERFORMANCE_COUNT': return `${company.performances.length}건`;
    case 'STAFF': return company.staff ? `총 ${company.staff.total_count}명 · ${company.staff.roles.map((r) => `${r.role_name} ${r.headcount}명`).join(' · ')}` : '프로필에 없음';
    case 'REGISTRATION_CERTIFICATION': return company.certifications.length ? company.certifications.map((item) => item.name).join(', ') : '프로필에 없음';
    case 'INDUSTRY': return company.industries.length ? company.industries.map((item) => item.name).join(', ') : '프로필에 없음';
    case 'REGION': return company.region_name ?? '프로필에 없음';
    case 'COMPANY_SIZE': return company.company_size;
    case 'EXPERIENCE_FIELD': {
      const fields = [...new Set(company.performances.flatMap((item) => item.fields))];
      return fields.length ? fields.join(', ') : '프로필에 없음';
    }
    default: return '프로필에 없음';
  }
}

export default function EvaluationPage() {
  const caseId = useSearchParams().get('caseId');
  const [workspace, setWorkspace] = useState<CaseWorkspace | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!caseId) return;
    loadCaseWorkspace(caseId).then(setWorkspace).catch((cause) => setError(cause instanceof Error ? cause.message : '평가 대응 데이터를 불러오지 못했습니다.'));
  }, [caseId]);

  const rows = useMemo(() => {
    if (!workspace?.currentAnalysisDetail) return [];
    return workspace.currentAnalysisDetail.requirements.filter((item) =>
      ['PERFORMANCE_AMOUNT', 'PERFORMANCE_COUNT', 'STAFF', 'REGISTRATION_CERTIFICATION', 'EXPERIENCE_FIELD', 'COMPANY_SIZE'].includes(item.type),
    ).map((requirement) => {
      const evidenceKey = requirement.evidence_keys[0];
      const evidence = evidenceKey ? workspace.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === evidenceKey) : null;
      const value = companyValue(requirement, workspace);
      return { requirement, evidence, value, ready: value !== '프로필에 없음' };
    });
  }, [workspace]);

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{error || <LoaderCircle className="size-7 animate-spin" />}</main>;

  const readyCount = rows.filter((item) => item.ready).length;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="evaluation" />

        <section className="mt-6 flex items-start gap-4 rounded-[24px] bg-[#edeafb] px-[26px] py-6">
          <div className="min-w-0 flex-1"><h2 className="text-[17px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">점수를 예측하지 않습니다</h2><p className="mt-2 text-[13.5px] leading-6">공고 원문에서 확인되는 평가 관련 조건과 회사 프로필 대응정보를 나란히 보여드립니다. 예상 심사점수는 계산하지 않으며, 준비된 정보와 추가 확인이 필요한 정보만 구분합니다.</p></div><div className="flex shrink-0 gap-2"><span className="rounded-full border border-[var(--product-line)] bg-white px-3 py-1 text-[12px]">값 있음 {readyCount}</span><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px]">확인 필요 {rows.length - readyCount}</span></div>
        </section>

        <section className="mt-8">
          <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">평가 기준 대응</h2><span className="text-[13.5px] text-[var(--product-muted)]">현재는 원문 근거와 회사 대응정보를 확인합니다</span></div>
          <div className="mt-3 overflow-hidden rounded-[20px] border border-[#eef0f4]">
            <div className="grid grid-cols-[minmax(0,1.5fr)_120px_minmax(0,1fr)_190px_150px] bg-[#f6f7f9] py-[13px] text-[12.5px] font-semibold text-[var(--product-muted)]"><div className="px-4">평가/대응 항목</div><div className="px-4">배점</div><div className="px-4">귀사 값</div><div className="px-4">근거</div><div className="px-4">상태</div></div>
            {rows.map(({ requirement, evidence, value, ready }) => <div key={requirement.requirement_key} className="grid min-h-[64px] grid-cols-[minmax(0,1.5fr)_120px_minmax(0,1fr)_190px_150px] items-center border-t border-[#eef0f4] text-[13.5px]"><div className="px-4"><strong className="block text-[14.5px]">{requirement.raw}</strong><span className="mt-1 block text-[12px] text-[var(--product-muted)]">{requirement.type}</span></div><div className="px-4 text-[var(--product-muted)]">원문 확인</div><div className="px-4">{value}</div><div className="px-4 text-[var(--product-accent)]">{evidence?.evidence_key ?? '근거 없음'}</div><div className="px-4"><span className={`rounded-full px-3 py-1 text-[12px] font-bold ${ready ? 'bg-[#e7f6ed] text-[#147a4a]' : 'bg-[#fbf0dc] text-[#8a5a00]'}`}>{ready ? '값 있음' : '확인 필요'}</span></div></div>)}
            {!rows.length && <div className="px-6 py-14 text-center text-[14px] text-[var(--product-muted)]">현재 분석에서 평가 대응에 연결된 원문 조건이 없습니다. 평가표 전용 구조화가 추가되면 이 영역에 별도로 표시됩니다.</div>}
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          {rows.filter((item) => item.evidence).slice(0, 4).map(({ requirement, evidence }) => <div key={requirement.requirement_key}><EvidenceQuote label={evidence!.evidence_key} quote={evidence!.quote} note="공고 원문 근거" /></div>)}
        </section>

        <section className="mt-8 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5 text-[13px] leading-6 text-[var(--product-muted)]">
          <strong className="text-[var(--product-ink)]">평가 대응 범위</strong><br />현재 화면은 공고 원문과 회사 대응정보를 검토하기 위한 화면입니다. 배점표 전용 구조화가 없는 항목은 배점이나 예상점수를 임의로 생성하지 않습니다.
        </section>
      </div>
    </main>
  );
}
