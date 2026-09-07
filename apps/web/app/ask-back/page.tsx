'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { answerQualificationQuestion, type QualificationQuestion } from '@/lib/qualification-api';
import { loadCaseWorkspace, workspaceHref, type CaseWorkspace } from '@/lib/case-workspace';

type AnswerChoice = 'yes' | 'no' | 'unknown';

export default function AskBackPage() {
  const searchParams = useSearchParams();
  const caseId = searchParams.get('caseId');
  const [workspace, setWorkspace] = useState<CaseWorkspace | null>(null);
  const [choice, setChoice] = useState<Record<string, AnswerChoice>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  async function reload() {
    if (!caseId) return;
    setError('');
    try {
      setWorkspace(await loadCaseWorkspace(caseId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 데이터를 불러오지 못했습니다.');
    }
  }

  useEffect(() => {
    void reload();
  }, [caseId]);

  const askable = workspace?.questions ?? [];
  const totalUnknown = workspace?.displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;
  const unaskable = Math.max(0, totalUnknown - askable.length);

  const evidenceByRequirement = useMemo(() => {
    const analysis = workspace?.currentAnalysisDetail;
    if (!analysis) return new Map<string, { label: string; quote: string }>();
    const map = new Map<string, { label: string; quote: string }>();
    for (const requirement of analysis.requirements) {
      const key = requirement.evidence_keys[0];
      const evidence = key ? analysis.evidence.find((item) => item.evidence_key === key) : null;
      if (evidence) map.set(requirement.requirement_key, { label: key, quote: evidence.quote });
    }
    return map;
  }, [workspace]);

  async function submit(question: QualificationQuestion) {
    if (!workspace?.sourceJudgment) return;
    const selected = choice[question.requirement_key] ?? 'unknown';
    if (selected === 'unknown') {
      setMessage('이 항목은 확인 필요 상태로 유지합니다.');
      return;
    }
    setBusyKey(question.requirement_key);
    setError('');
    setMessage('');
    try {
      await answerQualificationQuestion(workspace.caseItem.id, {
        source_judgment_run_id: workspace.sourceJudgment.id,
        requirement_key: question.requirement_key,
        satisfies_requirement: selected === 'yes',
        normalized_value: values[question.requirement_key]?.trim() || undefined,
        evidence_held: selected === 'yes',
      });
      await reload();
      setMessage('답변한 Requirement만 부분 재판정했습니다. 이 답은 이번 검토의 판정 근거로 저장됩니다.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '답변 저장에 실패했습니다.');
    } finally {
      setBusyKey(null);
    }
  }

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{error || <LoaderCircle className="size-7 animate-spin" />}</main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="questions" />

        {(error || message) && <div className={`mt-5 rounded-[14px] border px-4 py-3 text-[13px] ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}

        <section className="mt-5 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-[19px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">확인 필요 {totalUnknown}건 중 <span className="text-[var(--product-accent)]">답하실 수 있는 것은 {askable.length}건</span>입니다</h2>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">나머지 {unaskable}건은 답을 받아도 판정이 바뀌지 않거나 공고 문구 자체가 모호한 항목이라 질문하지 않습니다.</p>
            </div>
            <div className="flex gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 됨 {askable.length}</span><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">묻지 않음 {unaskable}</span></div>
          </div>
        </section>

        <div className="mt-4 space-y-4">
          {askable.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);
            const selected = choice[question.requirement_key] ?? 'unknown';
            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex items-center gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정됩니다</span><span className="text-[12.5px] text-[var(--product-muted)]">{question.requirement_type}</span></div>
                <h3 className="mt-3 text-[19px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">{question.question}</h3>
                <p className="mt-3 text-[13.5px] text-[var(--product-muted)]">회사 프로필에 비교할 값이 없어 판정하지 못한 조건입니다.</p>
                {evidence && <div className="mt-4"><EvidenceQuote label={evidence.label} quote={evidence.quote} /></div>}

                <div className="mt-5 space-y-2">
                  {[
                    ['yes', '있습니다 / 충족합니다', '입력한 값으로 이 Requirement만 다시 판정합니다'],
                    ['no', '없습니다 / 충족하지 않습니다', '이 Requirement는 미달로 재판정됩니다'],
                    ['unknown', '모르겠습니다', '판정하지 않고 확인 필요로 남깁니다'],
                  ].map(([value, label, help]) => (
                    <button key={value} type="button" onClick={() => setChoice((current) => ({ ...current, [question.requirement_key]: value as AnswerChoice }))} className={`flex w-full items-center gap-3 rounded-[20px] border px-[18px] py-[15px] text-left ${selected === value ? 'border-[var(--product-accent)] bg-[#edeafb]' : 'border-[var(--product-line)] bg-white'}`}>
                      <span className={`grid size-[18px] place-items-center rounded-full border ${selected === value ? 'border-[var(--product-accent)]' : 'border-[var(--product-line)]'}`}>{selected === value && <span className="size-[9px] rounded-full bg-[var(--product-accent)]" />}</span>
                      <strong className="text-[14.5px]">{label}</strong><span className="text-[12.5px] text-[var(--product-muted)]">{help}</span>
                    </button>
                  ))}
                </div>

                <div className="mt-[18px] flex flex-wrap items-center gap-3">
                  <Input value={values[question.requirement_key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [question.requirement_key]: event.target.value }))} className="h-[46px] max-w-[260px] rounded-full" placeholder="값 또는 메모 입력" disabled={selected !== 'yes'} />
                  <span className="text-[12.5px] text-[var(--product-muted)]">이 답은 이번 검토의 판정 근거로 저장됩니다</span>
                  <Button className="h-[46px] rounded-full px-[26px]" onClick={() => void submit(question)} disabled={busyKey !== null}>{busyKey === question.requirement_key && <LoaderCircle className="animate-spin" />} 저장하고 다시 판정</Button>
                </div>
              </section>
            );
          })}

          {unaskable > 0 && <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6"><div className="flex items-center gap-2"><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">묻지 않습니다</span><span className="text-[12.5px] text-[var(--product-muted)]">공고 문구 모호 / 근거 부족</span></div><h3 className="mt-3 text-[18px] font-bold">답변으로 해결할 수 없는 확인 필요 항목 {unaskable}건</h3><p className="mt-2 text-[13.5px] text-[var(--product-muted)]">잘못 이해한 조건을 사용자에게 되묻지 않습니다. 근거 원문에서 직접 확인해 주세요.</p><Link href={workspaceHref('/evidence', workspace.caseItem.id)}><Button variant="outline" className="mt-4 rounded-full">근거 원문 대조</Button></Link></section>}
        </div>
      </div>
    </main>
  );
}
