import type { ReactNode } from 'react';
import type { QualificationDetail } from '@/lib/qualification-detail';
import { qualificationDetailView } from '@/lib/qualification-detail-view';
import { STATE_TONE_CLASS } from '@/lib/qualification-state';

export function QualificationStateSummary({ detail, action }: { detail: QualificationDetail; action?: ReactNode }) {
  const view = qualificationDetailView(detail);
  const state = detail.state;
  return <section className={`rounded-[20px] border px-6 py-5 ${STATE_TONE_CLASS[view.tone]}`} aria-labelledby="qualification-conclusion">
    <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <p className="text-[15px] font-semibold">판정 요약</p>
        <h2 id="qualification-conclusion" className="mt-1 text-[28px] font-extrabold">{view.label}</h2>
        <p className="mt-2 text-[15px] leading-6">{view.description}</p>
        {view.historical && <p className="mt-2 text-sm">{view.historical}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {([['충족', view.counts?.satisfied], ['확인 필요', view.counts?.unknown], ['미달', view.counts?.unsatisfied]] as const).map(([label, value]) =>
          <div key={label} className="min-w-[88px] rounded-2xl bg-white px-4 py-3 text-center text-[var(--product-ink)]">
            <span className="block text-xs">{label}</span><strong className="mt-1 block text-[28px]">{value ?? '—'}</strong>
          </div>)}
        {action}
      </div>
    </div>
    <p className="mt-4 text-sm">분석 범위: {view.coverage}</p>
    <p className="mt-1 text-sm">저장 기준일: {state.stored_reference_date ?? '없음'} · 판정 규칙: {state.scope.rule_version}</p>
    {view.warnings.length > 0 && <ul className="mt-3 space-y-1 text-sm" aria-label="판정 기준 확인사항">{view.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
    <details className="mt-3 text-xs"><summary className="cursor-pointer">분석·판정 기준 ID</summary>
      <p className="mt-2 break-all">분석: {state.analysis_run_id ?? '없음'}<br />선택 판정: {state.selected_judgment_run_id ?? '없음'}</p>
    </details>
  </section>;
}
