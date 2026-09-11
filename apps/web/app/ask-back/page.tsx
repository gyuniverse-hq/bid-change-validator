'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo } from 'react';
import { LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import type { EvidenceLocation } from '@/lib/qualification-api';
import { REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import { Button } from '@/components/ui/button';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { isLocked } from '@/lib/copilot-actions';

import { useCaseWorkspace, workspaceHref } from '@/lib/case-workspace';



export default function AskBackPage() {
  const caseId = useSearchParams().get('caseId');
  return <AskBackWorkspace key={caseId} caseId={caseId} />;
}

function AskBackWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const { controller, action } = useActions(caseId ?? '');
  useEffect(() => {
    if (action.stage === 'COMPLETED') void reload();
  }, [action.stage, action.result?.result_judgment_run_id, reload]);

  const allQuestions = workspace?.questions ?? [];
  const askable = allQuestions.filter((item) => item.askable);
  const unaskable = allQuestions.filter((item) => !item.askable);
  const totalUnknown = workspace?.displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;

  const evidenceByRequirement = useMemo(() => {
    const analysis = workspace?.currentAnalysisDetail;
    if (!analysis) return new Map<string, { key: string; quote: string; location: EvidenceLocation }>();
    const map = new Map<string, { key: string; quote: string; location: EvidenceLocation }>();
    for (const requirement of analysis.requirements) {
      const key = requirement.evidence_keys[0];
      const evidence = key ? analysis.evidence.find((item) => item.evidence_key === key) : null;
      if (evidence) map.set(requirement.requirement_key, { key, quote: evidence.quote, location: evidence.location });
    }
    return map;
  }, [workspace]);

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{loadError || <LoaderCircle className="size-7 animate-spin" />}</main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="questions" />

        <ActionCard caseId={caseId} />

        <section className="mt-5 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-[19px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">확인 필요 {totalUnknown}건 중 <span className="text-[var(--product-accent)]">답하실 수 있는 것은 {askable.length}건</span>입니다</h2>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">복합·예외·법적 절차 조건은 사용자 Yes/No 답변만으로 판정하지 않습니다. 해당 조건은 원문 검토 대상으로 남깁니다.</p>
            </div>
            <div className="flex gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 됨 {askable.length}</span><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">묻지 않음 {unaskable.length}</span></div>
          </div>
        </section>

        <div className="mt-4 space-y-4">
          {askable.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);

            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex items-center gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정됩니다</span><span className="text-[12.5px] text-[var(--product-muted)]">{labelOf(REQUIREMENT_TYPE_LABEL, question.requirement_type)}</span></div>
                <h3 className="mt-3 text-[19px] font-bold leading-8 tracking-[-0.03em] text-[var(--product-ink)]">{question.question}</h3>
                <p className="mt-3 text-[13.5px] text-[var(--product-muted)]">저장된 판정에서 사용자 답변을 요청한 요건입니다. 답변과 증빙 보유 여부를 선택한 뒤 제안 내용을 확인해 주세요.</p>
                {evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}

                <Button className="mt-4 rounded-full" disabled={isLocked(action)}
                  onClick={() => void controller.beginAnswer(caseId, question.requirement_key, workspace.displayJudgment?.id)}>
                  이 요건 답변 입력 · 아직 저장 안 함
                </Button>
              </section>
            );
          })}

          {unaskable.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);
            return <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6"><div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">묻지 않습니다</span></div><h3 className="mt-3 text-[18px] font-bold">{question.raw_requirement}</h3><p className="mt-2 text-[13.5px] text-[var(--product-muted)]">{question.askability_reason}</p>{evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}<Link href={`${workspaceHref('/evidence', workspace.caseItem.id)}&evidence=${encodeURIComponent(evidence?.key ?? '')}`}><Button variant="outline" className="mt-4 rounded-full">근거 원문에서 확인</Button></Link></section>;
          })}

          {totalUnknown === 0 && <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-12 text-center"><h3 className="text-[19px] font-bold">{workspace.displayJudgment ? '지금 답하실 확인 필요 항목이 없습니다' : '현재 분석의 판정이 필요합니다'}</h3><p className="mt-2 text-[13.5px] text-[var(--product-muted)]">판정 결과에서 사용자 확인이 필요한 항목이 생기면 이 화면에 표시됩니다.</p><Link href={workspaceHref('/qualification', workspace.caseItem.id)}><Button variant="outline" className="mt-5 rounded-full">참가자격 검토로 돌아가기</Button></Link></section>}
        </div>
      </div>
    </main>
  );
}
