'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo } from 'react';
import { GitCompareArrows, LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { Button } from '@/components/ui/button';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { isLocked } from '@/lib/copilot-actions';
import { baselineVersion, currentVersion, useCaseWorkspace } from '@/lib/case-workspace';

function formatDate(value: string | null | undefined) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

function money(value: number | null | undefined) {
  return value == null ? '-' : `${value.toLocaleString()} 원`;
}

export default function ChangesPage() {
  const caseId = useSearchParams().get('caseId');
  return <ChangesWorkspace key={caseId} caseId={caseId} />;
}

function ChangesWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const { controller, action } = useActions(caseId ?? '');
  const result = action.result && 'revalidated_keys' in action.result ? action.result : null;
  const busy = isLocked(action);
  useEffect(() => {
    if (action.stage === 'COMPLETED') void reload();
  }, [action.stage, action.result?.result_judgment_run_id, reload]);

  const comparison = useMemo(() => {
    if (!workspace) return [];
    const base = baselineVersion(workspace);
    if (!base) return [];
    const current = currentVersion(workspace);
    return [
      ['입찰서 제출마감', formatDate(base.bid_closed_at), formatDate(current.bid_closed_at)],
      ['추정가격', money(base.estimated_price), money(current.estimated_price)],
      ['배정예산', money(base.allocated_budget), money(current.allocated_budget)],
      ['계약방법', base.contract_method ?? '-', current.contract_method ?? '-'],
      ['첨부문서 수', `${base.documents.length}종`, `${current.documents.length}종`],
    ];
  }, [workspace]);

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{loadError || <LoaderCircle className="size-7 animate-spin" />}</main>;

  const baseline = baselineVersion(workspace);
  const canRevalidate = Boolean(workspace.sourceJudgment && workspace.baselineAnalysis && workspace.currentAnalysis && baseline);

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="changes" />

        <ActionCard caseId={caseId} />

        <section className="mt-8">
          <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">공고 차수</h2><span className="text-[13.5px] text-[var(--product-muted)]">판정은 차수에 묶입니다</span></div>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {workspace.versions.map((version) => <article key={version.id} className={`rounded-[20px] border px-5 py-[18px] ${version.version_number === workspace.caseItem.current_version_number ? 'border-[var(--product-accent)] bg-[#edeafb]' : 'border-[var(--product-line)] bg-white'}`}><div className="flex items-center gap-2"><strong className="text-[14.5px]">{version.version_number}차 {version.version_number === 1 ? '공고' : '변경'}</strong>{version.version_number === workspace.caseItem.current_version_number && <span className="rounded-full bg-white px-2 py-1 text-[11px] font-bold">현재 판정 기준</span>}</div><p className="mt-2 text-[12.5px] text-[var(--product-muted)]">{formatDate(version.changed_at ?? version.posted_at ?? version.collected_at)}</p><p className="mt-2 text-[13px]">{version.change_reason ?? (version.version_number === 1 ? '최초 공고' : '변경 사유 미기재')}</p></article>)}
          </div>
        </section>

        {!baseline ? (
          <section className="mt-8 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-12 text-center">
            <h2 className="text-[20px] font-extrabold tracking-[-0.03em]">아직 변경 이력이 없습니다</h2>
            <p className="mt-3 text-[13.5px] leading-6 text-[var(--product-muted)]">현재 검토 건은 최초 공고만 존재합니다. 변경공고가 수집되면 이전 차수와 현재 차수를 비교하고, 바뀐 자격조건만 다시 판정합니다.</p>
          </section>
        ) : (
          <>
            <section className="mt-8">
              <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">기준 → 현재 대비</h2><span className="text-[13.5px] text-[var(--product-muted)]">나라장터 수집 값끼리 비교합니다</span></div>
              <div className="mt-3 overflow-hidden rounded-[20px] border border-[#eef0f4]">
                <div className="grid grid-cols-[270px_minmax(0,1fr)_minmax(0,1.4fr)_220px] bg-[#f6f7f9] py-[13px] text-[12.5px] font-semibold text-[var(--product-muted)]"><div className="px-4">항목</div><div className="px-4">기준 차수</div><div className="px-4">현재 차수</div><div className="px-4">판정 영향</div></div>
                {comparison.map(([label, before, after]) => {
                  const changed = before !== after;
                  return <div key={label} className="grid min-h-[54px] grid-cols-[270px_minmax(0,1fr)_minmax(0,1.4fr)_220px] items-center border-t border-[#eef0f4] text-[13.5px]"><div className="px-4 font-semibold">{label}</div><div className="px-4 text-[var(--product-muted)]">{before}</div><div className="px-4 font-semibold">{after}</div><div className="px-4"><span className={`rounded-full px-3 py-1 text-[12px] font-bold ${changed ? 'bg-[#fbf0dc] text-[#8a5a00]' : 'bg-[#f6f7f9]'}`}>{changed ? '변경됨' : '변경 없음'}</span></div></div>;
                })}
              </div>
            </section>

            <section className="mt-8 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><h2 className="text-[18px] font-bold">변경공고로 다시 판정할 항목</h2><p className="mt-2 text-[13.5px] text-[var(--product-muted)]">변경된 참가자격 요건 전체를 비교해 재검증합니다. 제안을 확인한 뒤 실행하며, 일부 요건만 선택하거나 제외할 수 없습니다.</p></div><Button onClick={() => void controller.propose(caseId, true)} disabled={!canRevalidate || busy} className="rounded-full">{busy ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 전체 변경 요건 재검증 제안</Button></div>
              {!canRevalidate && <p className="mt-4 text-[12.5px] text-[var(--product-muted)]">기준/현재 분석과 기준 판정이 모두 준비되어야 실행할 수 있습니다.</p>}
              {result && <div className="mt-5"><div className="mb-3 text-[14px]">실제 재판정 <strong>{result.revalidated_keys.length}건</strong></div><div className="overflow-hidden rounded-[18px] border border-[#eef0f4]">{result.changes.filter((item) => item.change_type !== 'UNCHANGED').map((item) => <div key={item.identity} className="grid grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)] border-t border-[#eef0f4] px-4 py-3 text-[13px] first:border-t-0"><strong>{item.change_type}</strong><span>{item.baseline_key ?? '-'}</span><span>{item.current_key ?? '-'}</span></div>)}</div></div>}
            </section>
          </>
        )}

        <section className="mt-8 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5 text-[13px] leading-6 text-[var(--product-muted)]">
          <strong className="text-[var(--product-ink)]">현재 Product Baseline 정책</strong><br />공고 변경값 자체는 NoticeVersion 원본 필드를 비교하고, 자격 판정 영향은 Backend Canonical Requirement Diff와 affected-only Revalidation 결과를 Source of Truth로 사용합니다.
        </section>
      </div>
    </main>
  );
}
