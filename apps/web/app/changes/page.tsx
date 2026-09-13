'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { GitCompareArrows, LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { Button } from '@/components/ui/button';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { currentRevalidation, isLocked } from '@/lib/copilot-actions';
import { baselineVersion, currentVersion, useCaseWorkspace } from '@/lib/case-workspace';
import { getQualificationAnalysis, type CanonicalRequirement, type QualificationAnalysisRun } from '@/lib/qualification-api';
import { CHANGE_TYPE_LABEL, labelOf, REQUIREMENT_TYPE_LABEL } from '@/lib/status-copy';

function formatDate(value: string | null | undefined) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

function money(value: number | null | undefined) {
  return value == null ? '-' : `${value.toLocaleString()} 원`;
}

/*
  구조화 값은 백엔드가 원문에서 뽑아낸 비교 대상이다.
  연산자(이상·포함 등)에 대응하는 한글 표가 아직 없으므로 값과 단위·기간만 적는다.
  「전라북도 이상」처럼 뜻을 지어내는 것보다 값만 보여주고 원문을 같이 두는 편이 정확하다.
*/
function requirementValue(requirement: CanonicalRequirement) {
  if (requirement.value == null) return '값 없음';
  const unit = requirement.unit ? ` ${requirement.unit}` : '';
  const period = requirement.period_months ? ` · 최근 ${requirement.period_months}개월` : '';
  return `${requirement.value}${unit}${period}`;
}

/** 재검증 결과 한 줄의 한쪽 차수. 요건이 없으면 왜 없는지를 적는다. */
function RequirementSide({ label, requirement, missing }: { label: string; requirement: CanonicalRequirement | null; missing: string }) {
  return (
    <div className="rounded-[14px] border border-[#eef0f4] bg-[#fafbfc] px-4 py-3">
      <span className="text-[12px] font-semibold text-[var(--product-muted)]">{label}</span>
      {requirement ? (
        <>
          <p className="mt-1.5 text-[13px] leading-6 text-[var(--product-ink)]">{requirement.raw}</p>
          <p className="mt-2 text-[12px] text-[var(--product-muted)]">구조화 값 · {requirementValue(requirement)}</p>
        </>
      ) : (
        <p className="mt-1.5 text-[13px] leading-6 text-[var(--product-muted)]">{missing}</p>
      )}
    </div>
  );
}

export default function ChangesPage() {
  const caseId = useSearchParams().get('caseId');
  return <ChangesWorkspace key={caseId} caseId={caseId} />;
}

function ChangesWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const { controller, action } = useActions(caseId ?? '');
  const result = currentRevalidation(action.result, {
    caseId: caseId ?? '', baselineAnalysisId: workspace?.baselineAnalysis?.id,
    currentAnalysisId: workspace?.currentAnalysis?.id, judgmentId: workspace?.displayJudgment?.id,
  });
  const hasPastResult = Boolean(action.result && 'revalidated_keys' in action.result && !result);
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

  /*
    재검증 결과는 요건 키(REQ-006-REGION)만 준다. 그 키가 무엇을 뜻하는지는 분석 상세에 있다.
    현재 차수 상세는 workspace가 이미 들고 있지만 기준 차수는 요약만 있어서 여기서 한 번 더 받는다.
    이게 없으면 화면이 내부 코드만 늘어놓게 되고, 무엇이 어떻게 바뀌었는지 읽을 수 없다.
  */
  const [baselineDetail, setBaselineDetail] = useState<{ analysisId: string; run: QualificationAnalysisRun } | null>(null);
  const baselineAnalysisId = workspace?.baselineAnalysis?.id;
  useEffect(() => {
    if (!baselineAnalysisId) return;
    let alive = true;
    void getQualificationAnalysis(baselineAnalysisId)
      .then((run) => { if (alive) setBaselineDetail({ analysisId: baselineAnalysisId, run }); })
      // 받지 못하면 원문 없이 키만 보여준다. 화면 전체를 실패로 만들 일은 아니다.
      .catch(() => { if (alive) setBaselineDetail(null); });
    return () => { alive = false; };
  }, [baselineAnalysisId]);

  /*
    어느 분석의 것인지 함께 담아둔다. effect 본문에서 동기적으로 비우면 렌더가 한 번 더 돌기 때문에
    (react-compiler EffectSetState) 지우는 대신, 지금 보고 있는 분석과 id가 맞을 때만 쓴다.
    검토 건을 옮겨 다닐 때 앞 건의 기준 차수 원문이 남아 보이는 것도 이걸로 막힌다.
  */
  const baselineRequirements = useMemo(
    () => new Map(
      (baselineDetail && baselineDetail.analysisId === baselineAnalysisId ? baselineDetail.run.requirements : [])
        .map((item) => [item.requirement_key, item]),
    ),
    [baselineDetail, baselineAnalysisId],
  );
  const currentRequirements = useMemo(
    () => new Map((workspace?.currentAnalysisDetail?.requirements ?? []).map((item) => [item.requirement_key, item])),
    [workspace?.currentAnalysisDetail],
  );

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container py-12">
    <ActionCard caseId={caseId} />
    <p role="alert">{loadError || '검토 데이터를 불러오고 있습니다.'}</p>
    {loadError && <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>}
  </main>;

  const baseline = baselineVersion(workspace);
  const canRevalidate = Boolean(workspace.sourceJudgment && workspace.baselineAnalysis && workspace.currentAnalysis && baseline);
  const affectedChanges = result?.changes.filter((item) => item.change_type !== 'UNCHANGED') ?? [];

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="changes" />

        <ActionCard caseId={caseId} />
        {hasPastResult && <p className="mt-3 text-sm text-[var(--product-muted)]">이전 분석 기준의 재검증 기록은 현재 결과 집계에 포함하지 않습니다.</p>}
        {loadError && <section role="alert" className="mt-4 rounded-xl border p-4">
          <p>작업 상태는 위에 유지됩니다. 화면 정보 갱신에 실패하여 마지막 조회 결과를 표시합니다.</p>
          <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>
        </section>}

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
            <section className="mt-8">{comparison.every(([, before, after]) => before === after) && <p className="mt-2 text-[13px] text-[var(--product-muted)]">주요 공고 정보에는 변경이 없습니다. (자격조건 자체의 변경 여부는 아래 재검증에서 확인하세요)</p>}
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
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><h2 className="text-[18px] font-bold">변경공고로 다시 판정할 항목</h2><p className="mt-2 text-[13.5px] text-[var(--product-muted)]">변경된 참가자격 요건 전체를 비교해 재검증합니다. 제안을 확인한 뒤 실행하며, 일부 요건만 선택하거나 제외할 수 없습니다.</p></div><Button onClick={() => void controller.propose(caseId, true)} disabled={!canRevalidate || busy || Boolean(loadError)} className="rounded-full">{busy ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 전체 변경 요건 재검증 제안</Button></div>
              {!canRevalidate && <p className="mt-4 text-[12.5px] text-[var(--product-muted)]">기준/현재 분석과 기준 판정이 모두 준비되어야 실행할 수 있습니다.</p>}
              {result && <div className="mt-5"><div className="mb-3 text-[14px]">영향 있는 변경 <strong>{affectedChanges.length}건</strong> · 다시 판정 <strong>{result.revalidated_keys.length}건</strong></div>{affectedChanges.length ? <div className="overflow-hidden rounded-[18px] border border-[#eef0f4]">{affectedChanges.map((item) => {
                const before = item.baseline_key ? baselineRequirements.get(item.baseline_key) ?? null : null;
                const after = item.current_key ? currentRequirements.get(item.current_key) ?? null : null;
                const typeCode = after?.type ?? before?.type ?? null;
                return (
                  <div key={item.identity} className="border-t border-[#eef0f4] px-4 py-4 first:border-t-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {/* 요건 유형을 못 찾으면 내부 키라도 보여준다. 빈 칸보다는 낫고, 못 찾았다는 사실도 드러난다. */}
                      <strong className="text-[14px]">{typeCode ? labelOf(REQUIREMENT_TYPE_LABEL, typeCode) : (item.current_key ?? item.baseline_key ?? item.identity)}</strong>
                      <span className="rounded-full bg-[#fbf0dc] px-2.5 py-0.5 text-[12px] font-bold text-[#8a5a00]">{CHANGE_TYPE_LABEL[item.change_type]}</span>
                    </div>
                    <div className="mt-3 grid gap-2 lg:grid-cols-2">
                      <RequirementSide label="기준 차수" requirement={before} missing={item.change_type === 'ADDED' ? '기준 차수에는 없던 요건입니다.' : '기준 차수 분석에서 이 요건을 찾지 못했습니다.'} />
                      <RequirementSide label="현재 차수" requirement={after} missing={item.change_type === 'REMOVED' ? '현재 차수에서 빠졌습니다.' : '현재 차수 분석에서 이 요건을 찾지 못했습니다.'} />
                    </div>
                  </div>
                );
              })}</div> : <p className="rounded-[18px] border border-dashed border-[#eef0f4] px-4 py-6 text-center text-[13px] text-[var(--product-muted)]">자격조건에 영향 있는 변경이 없습니다. 기존 판정이 그대로 유지됩니다.</p>}</div>}            </section>
          </>
        )}

        <section className="mt-8 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5 text-[13px] leading-6 text-[var(--product-muted)]">
          <strong className="text-[var(--product-ink)]">현재 판정 반영 기준</strong><br />공고 값 변경은 나라장터 수집 값끼리 비교하고, 자격 판정 영향은 백엔드의 자격조건 비교와 다시 판정한 결과를 기준으로 표시합니다.
      </section>
      </div>
    </main>
  );
}
