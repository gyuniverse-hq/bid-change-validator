'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import type { EvidenceLocation } from '@/lib/qualification-api';
import { REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { answerQualificationQuestion, type QualificationQuestion } from '@/lib/qualification-api';
import { useCaseWorkspace, workspaceHref } from '@/lib/case-workspace';

type AnswerChoice = 'yes' | 'no' | 'unknown';

export default function AskBackPage() {
  const caseId = useSearchParams().get('caseId');
  return <AskBackWorkspace key={caseId} caseId={caseId} />;
}

function AskBackWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const [choice, setChoice] = useState<Record<string, AnswerChoice>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [showSkipped, setShowSkipped] = useState(false);

  const allQuestions = workspace?.questions ?? [];
  const askable = allQuestions.filter((item) => item.askable);
  const unaskable = allQuestions.filter((item) => !item.askable);
  const totalJudgments = workspace?.displayJudgment?.judgments.length ?? 0;
  const totalUnknown = workspace?.displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;
  const resolvedCount = Math.max(totalJudgments - totalUnknown, 0);

  const askableVisible = askable.filter((item) => !skipped.has(item.requirement_key));
  const askableSkipped = askable.filter((item) => skipped.has(item.requirement_key));

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

  function skip(requirementKey: string) {
    setSkipped((current) => {
      const next = new Set(current);
      next.add(requirementKey);
      return next;
    });
  }

  function unskip(requirementKey: string) {
    setSkipped((current) => {
      const next = new Set(current);
      next.delete(requirementKey);
      return next;
    });
  }

  async function submit(question: QualificationQuestion) {
    if (!workspace?.displayJudgment || !question.askable) return;
    const selected = choice[question.requirement_key] ?? 'unknown';
    if (selected === 'unknown') {
      setMessage('이 항목은 답변 없이 확인 필요 상태로 남겨둡니다.');
      return;
    }
    setBusyKey(question.requirement_key);
    setError('');
    setMessage('');
    try {
      await answerQualificationQuestion(workspace.caseItem.id, {
        source_judgment_run_id: workspace.displayJudgment.id,
        requirement_key: question.requirement_key,
        satisfies_requirement: selected === 'yes',
        normalized_value: values[question.requirement_key]?.trim() || undefined,
        evidence_held: false,
      });
      await reload();
      setMessage('답변한 항목만 다시 판정했습니다. 이 답은 이번 검토의 판정 근거로 남습니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '답변 저장에 실패했습니다.');
    } finally {
      setBusyKey(null);
    }
  }

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{loadError || error || <LoaderCircle className="size-7 animate-spin" />}</main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="questions" />

        {(error || message) && <div className={`mt-5 rounded-[14px] border px-4 py-3 text-[13px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

        <section className="mt-5 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-[19px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">확인 필요 {totalUnknown}건 중 <span className="text-[var(--product-accent)]">답할 수 있는 것은 {askable.length}건</span>입니다</h2>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">복합·예외·법적 요건은 사용자 답변만으로 판정하지 않습니다. 해당 조건은 원문 검토 대상으로 남겨둡니다.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {/* 사용자가 직접 답한 개수가 아니라 자동 판정까지 포함한 값이라 「진행」이 아니라 「판정 완료」로 쓴다 */}
              {totalJudgments > 0 && <span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold text-[var(--product-muted)]">판정 완료 {resolvedCount}/{totalJudgments}</span>}
              <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정 {askable.length}</span>
              <span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">물을 수 없음 {unaskable.length}</span>
            </div>
          </div>
        </section>

        <div className="mt-4 space-y-4">
          {askableVisible.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);
            const selected = choice[question.requirement_key] ?? 'unknown';
            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정합니다</span>
                    <span className="text-[12.5px] text-[var(--product-muted)]">{labelOf(REQUIREMENT_TYPE_LABEL, question.requirement_type)}</span>
                  </div>
                  <button type="button" onClick={() => skip(question.requirement_key)} className="shrink-0 text-[12.5px] font-semibold text-[var(--product-muted)] underline underline-offset-2 hover:text-[var(--product-ink)]">이번 화면에서 건너뛰기</button>
                </div>
                <h3 className="mt-3 text-[19px] font-bold leading-8 tracking-[-0.03em] text-[var(--product-ink)]">{question.question}</h3>
                <p className="mt-3 text-[13.5px] text-[var(--product-muted)]">회사 프로필에 비교할 값이 없어, 귀사 답변으로만 안전하게 판정할 수 있는 조건입니다.</p>
                {evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}

                <div className="mt-5 space-y-2">
                  {[
                    ['yes', '있습니다 / 충족합니다', '입력한 답으로 이 항목만 다시 판정합니다'],
                    ['no', '없습니다 / 충족하지 않습니다', '이 항목은 미달로 판정됩니다'],
                    ['unknown', '모르겠습니다', '답변으로 저장하지 않고 확인 필요로 유지합니다'],
                  ].map(([value, label, help]) => (
                    <button key={value} type="button" onClick={() => setChoice((current) => ({ ...current, [question.requirement_key]: value as AnswerChoice }))} className={`flex w-full items-center gap-3 rounded-[20px] border px-[18px] py-[15px] text-left ${selected === value ? 'border-[var(--product-accent)] bg-[#edeafb]' : 'border-[var(--product-line)] bg-white'}`}>
                      <span className={`grid size-[18px] place-items-center rounded-full border ${selected === value ? 'border-[var(--product-accent)]' : 'border-[var(--product-line)]'}`}>{selected === value && <span className="size-[9px] rounded-full bg-[var(--product-accent)]" />}</span>
                      <strong className="text-[14.5px]">{label}</strong><span className="text-[12.5px] text-[var(--product-muted)]">{help}</span>
                    </button>
                  ))}
                </div>

                <div className="mt-[18px] flex flex-wrap items-center gap-3">
                  <Input value={values[question.requirement_key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [question.requirement_key]: event.target.value }))} className="h-[46px] max-w-[260px] rounded-full" placeholder="값이나 메모 입력" disabled={selected !== 'yes'} />
                  <span className="text-[12.5px] text-[var(--product-muted)]">이 답은 이번 검토의 판정 근거로만 저장됩니다</span>
                  <Button className="h-[46px] rounded-full px-[26px]" onClick={() => void submit(question)} disabled={busyKey !== null}>{busyKey === question.requirement_key && <LoaderCircle className="animate-spin" />} {selected === 'unknown' ? '확인 필요로 유지' : '저장하고 다시 판정'}</Button>
                </div>
              </section>
            );
          })}

          {askableSkipped.length > 0 && (
            <section className="rounded-[20px] border border-dashed border-[#eef0f4] bg-[#fafbfc] px-[26px] py-4">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <button type="button" onClick={() => setShowSkipped((v) => !v)} className="text-[13px] font-semibold text-[var(--product-muted)]">
                  건너뛴 항목 {askableSkipped.length}개 {showSkipped ? '접기 ▲' : '보기 ▼'}
                </button>
                {/* skipped는 화면 state라 저장되지 않는다. 저장된 상태로 오해하지 않도록 명시한다. */}
                <span className="text-[12px] text-[var(--product-faint)]">이 화면에서만 숨긴 상태로, 새로고침하면 다시 나타납니다</span>
              </div>
              {showSkipped && (
                <ul className="mt-3 space-y-2">
                  {askableSkipped.map((question) => (
                    <li key={question.requirement_key} className="flex items-center justify-between gap-3 text-[13px]">
                      <span className="text-[var(--product-ink)]">{question.question}</span>
                      <button type="button" onClick={() => unskip(question.requirement_key)} className="shrink-0 font-semibold text-[var(--product-accent-deep)]">다시 보기</button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {unaskable.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);
            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">물을 수 없습니다</span></div>
                <h3 className="mt-3 text-[18px] font-bold">{question.raw_requirement}</h3>
                <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">{question.askability_reason}</p>
                {evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}
                {evidence && (
                  <Link href={`${workspaceHref('/evidence', workspace.caseItem.id)}&evidence=${encodeURIComponent(evidence.key)}`}>
                    <Button variant="outline" className="mt-4 rounded-full">근거 원문에서 확인</Button>
                  </Link>
                )}
              </section>
            );
          })}

          {totalUnknown === 0 && (
            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-12 text-center">
              <h3 className="text-[19px] font-bold">{workspace.displayJudgment ? '지금 답할 확인 필요 항목이 없습니다' : '아직 분석과 판정이 필요합니다'}</h3>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">판정 결과에서 사용자 확인이 필요한 항목이 생기면 이 화면에 표시합니다</p>
              <Link href={workspaceHref('/qualification', workspace.caseItem.id)}>
                <Button variant="outline" className="mt-5 rounded-full">참가자격 검토로 돌아가기</Button>
              </Link>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}