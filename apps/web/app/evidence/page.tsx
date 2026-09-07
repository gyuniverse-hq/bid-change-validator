'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { Button } from '@/components/ui/button';
import { absoluteApiUrl, getDocumentText, type NoticeDocument, type NoticeDocumentText } from '@/lib/api';
import { currentVersion, loadCaseWorkspace, workspaceHref, type CaseWorkspace } from '@/lib/case-workspace';

function displayLocation(location: Record<string, unknown>) {
  const display = location.display;
  if (typeof display === 'string' && display) return display;
  const page = location.page;
  const clause = location.clause_label;
  return [clause, page != null ? `p.${page}` : null].filter(Boolean).join(' ') || '위치 정보 없음';
}

function blockText(block: Record<string, unknown>) {
  for (const key of ['text', 'content', 'raw', 'paragraph_text']) {
    const value = block[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export default function EvidencePage() {
  const searchParams = useSearchParams();
  const caseId = searchParams.get('caseId');
  const evidenceParam = searchParams.get('evidence');
  const [workspace, setWorkspace] = useState<CaseWorkspace | null>(null);
  const [documentId, setDocumentId] = useState('');
  const [documentText, setDocumentText] = useState<NoticeDocumentText | null>(null);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState(evidenceParam ?? '');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!caseId) return;
    loadCaseWorkspace(caseId).then((value) => {
      setWorkspace(value);
      const version = currentVersion(value);
      const evidenceDoc = evidenceParam
        ? value.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === evidenceParam)?.document_id
        : null;
      setDocumentId(evidenceDoc ?? version.documents[0]?.id ?? '');
      if (!selectedEvidenceKey) setSelectedEvidenceKey(value.currentAnalysisDetail?.evidence[0]?.evidence_key ?? '');
    }).catch((cause) => setError(cause instanceof Error ? cause.message : '근거 데이터를 불러오지 못했습니다.'));
  }, [caseId, evidenceParam]);

  const version = workspace ? currentVersion(workspace) : null;
  const document = version?.documents.find((item) => item.id === documentId) ?? null;

  useEffect(() => {
    if (!document) {
      setDocumentText(null);
      return;
    }
    getDocumentText(document.text_url).then(setDocumentText).catch(() => setDocumentText(null));
  }, [document?.id]);

  const evidence = workspace?.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === selectedEvidenceKey) ?? null;
  const requirement = evidence
    ? workspace?.currentAnalysisDetail?.requirements.find((item) => item.evidence_keys.includes(evidence.evidence_key)) ?? null
    : null;
  const judgment = requirement
    ? workspace?.displayJudgment?.judgments.find((item) => item.requirement_key === requirement.requirement_key) ?? null
    : null;

  const nearbyEvidence = useMemo(() => {
    if (!workspace?.currentAnalysisDetail) return [];
    return workspace.currentAnalysisDetail.evidence.slice(0, 8);
  }, [workspace]);

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{error || <LoaderCircle className="size-7 animate-spin" />}</main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="evidence" />

        <div className="mt-5 flex flex-wrap gap-2">
          {version?.documents.map((item) => (
            <button key={item.id} type="button" onClick={() => setDocumentId(item.id)} className={`h-10 rounded-full px-5 text-[14px] font-semibold ${documentId === item.id ? 'bg-[var(--product-ink)] text-white' : 'border border-[var(--product-line)] bg-white'}`}>{item.name}</button>
          ))}
        </div>

        <section className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,862px)_minmax(360px,470px)]">
          <div className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
            <div className="flex flex-wrap items-center gap-3 border-b border-[var(--product-line)] pb-[14px]">
              <strong className="text-[14px]">{document?.name ?? '문서 없음'}</strong>
              <span className="text-[12.5px] text-[var(--product-muted)]">{document?.extraction_status ?? '-'}</span>
              {document && <a href={absoluteApiUrl(document.render_source_url)} target="_blank" rel="noreferrer" className="ml-auto"><Button variant="outline" size="sm">원본 열기</Button></a>}
            </div>

            <div className="mt-3 max-h-[620px] overflow-y-auto pr-2">
              {documentText?.blocks?.length ? documentText.blocks.map((block, index) => {
                const text = blockText(block);
                if (!text) return null;
                const active = evidence?.quote && text.includes(evidence.quote.slice(0, Math.min(24, evidence.quote.length)));
                return <div key={index} className={`flex gap-4 rounded-[20px] px-[18px] py-[14px] text-[14.5px] leading-[1.85] ${active ? 'bg-[#fbf0dc] font-semibold' : ''}`}><span className="w-10 shrink-0 text-[13px] font-semibold text-[var(--product-muted)]">{index + 1}</span><p>{text}</p></div>;
              }) : documentText?.text ? <pre className="whitespace-pre-wrap text-[14px] leading-7 text-[var(--product-body)]">{documentText.text}</pre> : <div className="grid min-h-[420px] place-items-center text-[14px] text-[var(--product-muted)]">추출 텍스트가 없습니다. 원본 열기로 확인해 주세요.</div>}
            </div>
            <p className="mt-4 text-[12.5px] text-[var(--product-muted)]">원문을 그대로 표시하며, 이 화면에서 문장을 요약하거나 고쳐 쓰지 않습니다.</p>
          </div>

          <aside className="space-y-4">
            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
              {evidence ? <>
                <div className="flex items-center gap-2"><span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">{judgment?.status === 'SATISFIED' ? '충족' : judgment?.status === 'UNSATISFIED' ? '미달' : '확인 필요'}</span><span className="text-[12.5px] text-[var(--product-muted)]">{displayLocation(evidence.location)}</span></div>
                <h2 className="mt-4 text-[18px] font-bold">{requirement?.raw ?? '판정 근거'}</h2>
                <div className="mt-4"><EvidenceQuote label={evidence.evidence_key} quote={evidence.quote} /></div>
                <div className="mt-4 divide-y divide-[var(--product-line-2)] text-[13px]"><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">판정</span><strong>{judgment?.status ?? '미판정'}</strong></div><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">판정 근거</span><span>{judgment?.basis_type ?? '-'}</span></div><div className="flex justify-between py-3"><span className="text-[var(--product-muted)]">Reason</span><span>{judgment?.reason_code ?? '-'}</span></div></div>
              </> : <p className="text-[14px] text-[var(--product-muted)]">선택할 Evidence가 없습니다.</p>}
            </section>

            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[22px] py-5">
              <div className="flex items-baseline justify-between"><h2 className="text-[18px] font-bold">같은 화면에서 볼 수 있는 근거</h2><span className="text-[12px] text-[var(--product-muted)]">{nearbyEvidence.length}건</span></div>
              <div className="mt-3 divide-y divide-[var(--product-line)]">{nearbyEvidence.map((item) => <button key={item.evidence_key} type="button" onClick={() => { setSelectedEvidenceKey(item.evidence_key); setDocumentId(item.document_id); }} className="flex w-full items-center justify-between gap-3 py-3 text-left"><span className="truncate text-[13px]">{item.quote}</span><span className="shrink-0 text-[12px] font-semibold text-[var(--product-accent)]">{displayLocation(item.location)}</span></button>)}</div>
            </section>

            <Link href={workspaceHref('/ask-back', workspace.caseItem.id)}><Button variant="outline" className="w-full rounded-full">확인 필요에 답하기</Button></Link>
          </aside>
        </section>
      </div>
    </main>
  );
}
