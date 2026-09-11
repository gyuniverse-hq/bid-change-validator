'use client';

/**
 * 05 평가 대응 — 제안서 대조 (v6, Figma 72:486)
 *
 * 왼쪽: 자격요건 표(기존) + 「제안서 위치」·「확인」 열
 * 오른쪽: 제안서 업로드 → 뷰어 + 선택 항목 후보 발췌 + 직접 검색
 * 원칙: 위치는 시스템이 찾고(키워드), 다뤘는지는 사용자가 판단 (00 §7.2 DL-001). 점수 없음.
 *
 * 파일 전체를 app/evaluation/page.tsx에 덮어쓴다.
 * 의존: lib/proposal-keywords.ts (신규), lib/status-copy.ts의 REQUIREMENT_TYPE_LABEL·labelOf (#85)
 */

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { FileText, LoaderCircle, Search, Upload } from 'lucide-react';

import { DocumentViewer } from '@/components/document-viewer';
import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getDocumentText, uploadProposalDocument, type ProposalDocument } from '@/lib/api';
import { useCaseWorkspace, type CaseWorkspace } from '@/lib/case-workspace';
import {
  PROPOSAL_CHECK_COPY,
  findProposalHits,
  formatBlockLocation,
  proposalCheckStorageKey,
  type ProposalBlock,
  type ProposalCheckState,
  type ProposalHit,
} from '@/lib/proposal-keywords';
import type { CanonicalRequirement } from '@/lib/qualification-api';
import { REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';

/** 05 표에 올리는 요건 유형. 업종·소재지는 사업자등록증으로 보는 항목이라 제안서 본문 대조 대상이 아니다. */
const PROPOSAL_CHECK_TYPES = ['PERFORMANCE_AMOUNT', 'PERFORMANCE_COUNT', 'STAFF', 'REGISTRATION_CERTIFICATION', 'EXPERIENCE_FIELD', 'COMPANY_SIZE'];
const CHECK_STATES: ProposalCheckState[] = ['CHECKED', 'PENDING', 'NOT_APPLICABLE'];
const NOT_FOUND_COPY = '찾지 못했습니다. 직접 확인해주세요';

type CheckMap = Record<string, ProposalCheckState>;

function loadChecks(key: string): CheckMap {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as CheckMap) : {};
  } catch {
    return {};
  }
}

function saveChecks(key: string, checks: CheckMap) {
  try {
    window.localStorage.setItem(key, JSON.stringify(checks));
  } catch {
    // 저장 못 해도 화면은 동작한다. 새 브라우저에서는 초기화된다.
  }
}

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
  return <EvaluationWorkspace key={caseId} caseId={caseId} />;
}

function EvaluationWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error, reload } = useCaseWorkspace(caseId);

  // ── 제안서 문서 · 추출 블록 ─────────────────────────────────────────────
  const proposalDoc: ProposalDocument | null = useMemo(() => {
    const docs = workspace?.caseItem.documents ?? [];
    const proposals = docs.filter((doc) => doc.role === 'PROPOSAL');
    const pick = proposals.length ? proposals : docs;
    return pick.length ? pick[pick.length - 1] : null;
  }, [workspace]);
  const extracted = proposalDoc?.extraction_status === 'EXTRACTED';

  // 동기 setState-in-effect 금지(팀 lint) → 상태는 docId와 함께 들고, 파생값으로 쓴다
  const [blocksState, setBlocksState] = useState<{ docId: string; blocks: ProposalBlock[] } | null>(null);
  const blocks = proposalDoc && extracted && blocksState?.docId === proposalDoc.id ? blocksState.blocks : null;
  const blocksLoading = Boolean(proposalDoc && extracted && !blocks);
  useEffect(() => {
    if (!proposalDoc || !extracted) return;
    let cancelled = false;
    const docId = proposalDoc.id;
    void getDocumentText(proposalDoc.text_url)
      .then((payload) => { if (!cancelled) setBlocksState({ docId, blocks: (payload.blocks ?? []) as unknown as ProposalBlock[] }); })
      .catch(() => { if (!cancelled) setBlocksState({ docId, blocks: [] }); });
    return () => { cancelled = true; };
  }, [proposalDoc, extracted]);

  // ── 사용자 판단 3상태 (localStorage, caseId + 제안서 문서 id) ───────────
  const storageKey = workspace && proposalDoc ? proposalCheckStorageKey(workspace.caseItem.id, proposalDoc.id) : null;
  const [checksState, setChecksState] = useState<{ key: string; map: CheckMap } | null>(null);
  const checks: CheckMap = useMemo(() => {
    if (!storageKey) return {};
    return checksState?.key === storageKey ? checksState.map : loadChecks(storageKey);
  }, [storageKey, checksState]);
  function setCheck(requirementKey: string, state: ProposalCheckState) {
    if (!storageKey) return;
    const next = { ...checks, [requirementKey]: state };
    saveChecks(storageKey, next);
    setChecksState({ key: storageKey, map: next });
  }

  // ── 표 행 ──────────────────────────────────────────────────────────────
  const rows = useMemo(() => {
    if (!workspace?.currentAnalysisDetail) return [];
    return workspace.currentAnalysisDetail.requirements
      .filter((item) => PROPOSAL_CHECK_TYPES.includes(item.type))
      .map((requirement) => {
        const evidenceKey = requirement.evidence_keys[0];
        const evidence = evidenceKey ? workspace.currentAnalysisDetail?.evidence.find((item) => item.evidence_key === evidenceKey) ?? null : null;
        const hits: ProposalHit[] | null = blocks ? findProposalHits(requirement.type, requirement.raw, blocks) : null;
        return { requirement, evidence, value: companyValue(requirement, workspace), hits };
      });
  }, [workspace, blocks]);

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected = rows.find((row) => row.requirement.requirement_key === selectedKey) ?? rows[0] ?? null;
  const stateOf = (key: string): ProposalCheckState => checks[key] ?? 'PENDING';
  const counts = { CHECKED: 0, PENDING: 0, NOT_APPLICABLE: 0 } as Record<ProposalCheckState, number>;
  rows.forEach((row) => { counts[stateOf(row.requirement.requirement_key)] += 1; });

  function selectNextPending() {
    const start = selected ? rows.indexOf(selected) + 1 : 0;
    const ordered = [...rows.slice(start), ...rows.slice(0, start)];
    const next = ordered.find((row) => stateOf(row.requirement.requirement_key) === 'PENDING');
    if (next) setSelectedKey(next.requirement.requirement_key);
  }

  // ── 직접 검색 ─────────────────────────────────────────────────────────
  const [query, setQuery] = useState('');
  const searchHits = useMemo(() => {
    const needle = query.trim();
    if (!needle || !blocks) return [];
    return blocks.filter((block) => block.text.includes(needle)).slice(0, 5).map((block) => {
      const index = block.text.indexOf(needle);
      const start = Math.max(0, index - 60);
      return { block, location: formatBlockLocation(block), excerpt: `${start > 0 ? '…' : ''}${block.text.slice(start, index + needle.length + 100).replace(/\s+/g, ' ')}…` };
    });
  }, [query, blocks]);

  // ── 업로드 ────────────────────────────────────────────────────────────
  const uploadInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  async function upload(file: File | undefined) {
    if (!workspace || !file) return;
    setUploading(true);
    setUploadError('');
    try {
      await uploadProposalDocument(workspace.caseItem.id, file);
      await reload();
      setSelectedKey(null);
    } catch (cause) {
      setUploadError(cause instanceof Error ? cause.message : '제안서 업로드에 실패했습니다.');
    } finally {
      if (uploadInput.current) uploadInput.current.value = '';
      setUploading(false);
    }
  }

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container grid min-h-[420px] place-items-center py-12">{error || <LoaderCircle className="size-7 animate-spin" />}</main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="evaluation" />

        {/* 배너 — 점수 없음, 개수만 */}
        <section className="mt-6 flex items-start gap-4 rounded-[24px] bg-[#edeafb] px-[26px] py-6">
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">점수를 예측하지 않습니다</h2>
            <p className="mt-2 text-[13.5px] leading-6">왼쪽은 공고가 요구한 항목, 오른쪽은 귀사가 올린 제안서입니다. 시스템은 관련 문구가 있을 만한 위치만 찾고, 그 항목을 다뤘는지는 직접 판단합니다. 몇 점을 받을지는 계산하지 않습니다.</p>
          </div>
          {proposalDoc && <div className="flex shrink-0 gap-2">
            <span className="rounded-full border border-[var(--product-line)] bg-white px-3 py-1 text-[12px]">확인함 {counts.CHECKED}</span>
            <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">아직 {counts.PENDING}</span>
            <span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px]">해당없음 {counts.NOT_APPLICABLE}</span>
          </div>}
        </section>

        <section className="mt-8">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[21px] font-extrabold tracking-[-0.035em]">공고 요구 항목 ↔ 제안서</h2>
            <span className="text-[13.5px] text-[var(--product-muted)]">위치는 시스템이 찾고, 다뤘는지는 직접 판단합니다</span>
            <span className="ml-auto text-[13px] text-[var(--product-muted)]">자격요건 {rows.length}건 · 제안서 {proposalDoc ? 1 : 0}건</span>
          </div>

          <div className="mt-3 grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            {/* ── 왼쪽: 요건 표 ── */}
            <div className="overflow-hidden rounded-[20px] border border-[#eef0f4] bg-white">
              <div className="grid grid-cols-[minmax(0,1.6fr)_140px_180px_220px] bg-[#f6f7f9] py-[13px] text-[12.5px] font-semibold text-[var(--product-muted)]"><div className="px-4">공고 요구 항목</div><div className="px-4">귀사 값</div><div className="px-4">제안서 위치</div><div className="px-4">확인</div></div>
              {rows.map(({ requirement, value, hits }) => {
                const key = requirement.requirement_key;
                const isSelected = selected?.requirement.requirement_key === key;
                const state = stateOf(key);
                const first = hits?.[0] ?? null;
                return (
                  <div key={key} className={`grid min-h-[64px] grid-cols-[minmax(0,1.6fr)_140px_180px_220px] items-stretch border-t border-[#eef0f4] text-[13.5px] ${isSelected ? 'bg-[#edeafb]' : 'hover:bg-[var(--product-tint)]'}`}>
                    <button type="button" onClick={() => setSelectedKey(key)} className="flex h-full w-full cursor-pointer flex-col justify-center bg-transparent px-4 py-3 text-left">
                      <strong className="block text-[14.5px]">{requirement.raw}</strong>
                      <span className="mt-1 block text-[12px] text-[var(--product-muted)]">{labelOf(REQUIREMENT_TYPE_LABEL, requirement.type)}</span>
                    </button>
                    <button type="button" onClick={() => setSelectedKey(key)} className={`flex h-full w-full cursor-pointer items-center bg-transparent px-4 text-left ${value === '프로필에 없음' ? 'text-[var(--product-faint)]' : ''}`}>{value}</button>
                    <button type="button" onClick={() => setSelectedKey(key)} className="flex h-full w-full cursor-pointer items-center bg-transparent px-4 text-left text-[13px]">
                      {!proposalDoc ? <span className="text-[var(--product-faint)]">제안서를 올리면 찾습니다</span>
                        : !extracted ? <span className="text-[var(--product-faint)]">텍스트를 추출하지 못했습니다</span>
                        : blocksLoading || hits === null ? <LoaderCircle className="size-4 animate-spin text-[var(--product-faint)]" />
                        : first ? <><span className="text-[var(--product-accent)]">{first.location}</span><span className="mt-0.5 block text-[11.5px] text-[var(--product-faint)]">후보 {hits.length}곳</span></>
                        : <span className="text-[var(--product-faint)]">{NOT_FOUND_COPY}</span>}
                    </button>
                    <div className="flex gap-1 px-4">
                      {CHECK_STATES.map((candidate) => {
                        const active = state === candidate;
                        const warn = candidate === 'PENDING';
                        return <button key={candidate} type="button" disabled={!proposalDoc} onClick={() => setCheck(key, candidate)} className={`rounded-full border px-2.5 py-0.5 text-[11.5px] disabled:opacity-40 ${active ? (warn ? 'border-[#8a5a00] bg-[#fbf0dc] font-bold text-[#8a5a00]' : 'border-[var(--product-accent)] bg-[#edeafb] font-bold text-[var(--product-accent-deep)]') : 'border-[var(--product-line)] text-[var(--product-faint)]'}`}>{PROPOSAL_CHECK_COPY[candidate]}</button>;
                      })}
                    </div>
                  </div>
                );              })}
              {!rows.length && <div className="px-6 py-14 text-center text-[14px] text-[var(--product-muted)]">현재 대조할 참가자격 조건이 없습니다. 참가자격 분석이 먼저 필요합니다.</div>}
            </div>

            {/* ── 오른쪽: 제안서 ── */}
            <div className="overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
              <input ref={uploadInput} type="file" accept=".pdf,.hwp,.hwpx,.txt,.docx" className="hidden" onChange={(event) => void upload(event.target.files?.[0])} />
              {!proposalDoc ? (
                <>
                  <div className="bg-[#f6f7f9] px-5 py-4"><strong className="block text-[14px] text-[var(--product-ink)]">제안서</strong><span className="mt-0.5 block text-[12px] text-[var(--product-muted)]">아직 올린 제안서가 없습니다</span></div>
                  <div className="p-5">
                    <div className="flex flex-col items-center gap-3 rounded-[14px] border border-dashed border-[var(--product-line)] bg-[var(--product-tint)] px-6 py-11 text-center">
                      <Upload className="size-6 text-[var(--product-muted)]" />
                      <strong className="text-[14px] text-[var(--product-ink)]">제안서를 올리면 공고 요구 항목마다 관련 위치를 찾아드립니다</strong>
                      <span className="text-[12.5px] text-[var(--product-muted)]">PDF · HWP · HWPX — 텍스트 추출이 되는 파일만 위치를 찾을 수 있습니다</span>
                      <Button onClick={() => uploadInput.current?.click()} disabled={uploading} className="mt-1 rounded-full px-5">{uploading ? <LoaderCircle className="animate-spin" /> : <FileText />} 제안서 올리기</Button>
                      {uploadError && <span className="text-[12.5px] text-[var(--product-bad)]">{uploadError}</span>}
                    </div>
                    <p className="mt-4 text-[12px] leading-5 text-[var(--product-faint)]">제안서는 이 검토 건에만 저장되고, 점수를 매기거나 대신 쓰지 않습니다.</p>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-3 bg-[#f6f7f9] px-5 py-4">
                    <div className="min-w-0 flex-1"><strong className="block text-[14px] text-[var(--product-ink)]">제안서</strong><span className="mt-0.5 block truncate text-[12px] text-[var(--product-muted)]">{proposalDoc.name} · {extracted ? `${proposalDoc.extracted_char_count?.toLocaleString() ?? '-'}자 추출됨` : '텍스트 추출 안 됨'}</span></div>
                    <Button variant="outline" size="sm" onClick={() => uploadInput.current?.click()} disabled={uploading} className="rounded-full">{uploading ? <LoaderCircle className="animate-spin" /> : '다른 파일 올리기'}</Button>
                  </div>
                  {uploadError && <p className="px-5 pt-3 text-[12.5px] text-[var(--product-bad)]">{uploadError}</p>}

                  <div className="px-5 pt-4">
                    <div className="flex h-10 items-center rounded-full border border-[var(--product-line)] px-4 focus-within:border-[var(--product-accent)]">
                      <Input value={query} onChange={(event) => setQuery(event.target.value)} disabled={!blocks} placeholder="제안서에서 직접 찾기 — 예: 투입인력" aria-label="제안서 직접 검색" className="h-auto flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" />
                      <Search className="size-4 text-[var(--product-muted)]" />
                    </div>
                    {query.trim() && <div className="mt-2 space-y-2">
                      {searchHits.length ? searchHits.map((hit) => <button key={hit.block.block_index} type="button" onClick={() => setQuery('')} className="block w-full rounded-[12px] border border-[#eef0f4] px-3 py-2 text-left"><span className="block text-[12.5px] font-semibold">{hit.location}</span><span className="mt-0.5 block text-[12px] leading-5 text-[var(--product-muted)]">{hit.excerpt}</span></button>)
                        : <p className="px-1 text-[12.5px] text-[var(--product-faint)]">「{query.trim()}」{NOT_FOUND_COPY}</p>}
                    </div>}
                  </div>

                  {selected && <div className="px-5 pt-5">
                    <div className="flex items-center gap-2"><strong className="min-w-0 flex-1 truncate text-[15px] text-[var(--product-ink)]">{selected.requirement.raw}</strong><span className="rounded-full border border-[var(--product-line)] px-2.5 py-0.5 text-[11.5px]">{labelOf(REQUIREMENT_TYPE_LABEL, selected.requirement.type)}</span></div>
                    {!extracted ? <p className="mt-2 text-[12.5px] text-[var(--product-muted)]">텍스트를 추출하지 못해 위치를 찾을 수 없습니다. 아래 뷰어에서 직접 확인해 주세요.</p>
                      : selected.hits === null ? <p className="mt-2 text-[12.5px] text-[var(--product-muted)]">제안서를 읽는 중입니다…</p>
                      : selected.hits.length ? <>
                        <p className="mt-2 text-[12.5px] text-[var(--product-muted)]">관련 문구 후보 {selected.hits.length}곳 · {[...new Set(selected.hits.flatMap((hit) => hit.matched))].slice(0, 4).map((word) => `「${word}」`).join('')}으로 찾았습니다</p>
                        <div className="mt-3 space-y-2">{selected.hits.map((hit, index) => <div key={hit.block.block_index} className={`rounded-[14px] border px-3.5 py-3 ${index === 0 ? 'border-[var(--product-accent)] bg-[#edeafb]' : 'border-[#eef0f4]'}`}><span className={`block text-[13px] font-semibold ${index === 0 ? 'text-[var(--product-accent-deep)]' : ''}`}>{hit.location}</span><span className="mt-1 block text-[12.5px] leading-5 text-[var(--product-muted)]">{hit.excerpt}</span></div>)}</div>
                      </>
                      : <p className="mt-2 text-[12.5px] text-[var(--product-muted)]">{NOT_FOUND_COPY}. 「확인」 열에서 해당없음이면 해당없음으로 표시해 주세요.</p>}
                    {selected.evidence && <div className="mt-3"><EvidenceQuote label="공고 원문 근거" quote={selected.evidence.quote} location={selected.evidence.location} /></div>}
                  </div>}

                  <div className="p-5">
                    <div className="flex items-baseline justify-between"><strong className="text-[13px] text-[var(--product-ink)]">제안서 원문</strong><span className="text-[12px] text-[var(--product-faint)]">{selected?.hits?.[0] ? `후보 1순위 ${selected.hits[0].location}` : ''}</span></div>
                    <div className="mt-2 flex h-[460px] flex-col overflow-hidden rounded-[12px] border border-[#eef0f4] bg-[var(--product-tint)]">
                      <DocumentViewer document={proposalDoc} emptyMessage="제안서를 불러오지 못했습니다." />
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </section>

        {/* 하단 스트립 */}
        <section className="mt-8 flex flex-col justify-between gap-4 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] px-6 py-5 text-[13px] leading-6 text-[var(--product-muted)] md:flex-row md:items-center">
          {proposalDoc ? <>
            <div><strong className="text-[var(--product-ink)]">{counts.PENDING ? `아직 확인하지 않은 항목이 ${counts.PENDING}개 있습니다.` : '모든 항목을 확인했습니다.'}</strong> 제출 전에 제안서에서 직접 확인해 주세요. 시스템은 위치 후보만 찾고 다뤘는지는 판단하지 않습니다.</div>
            {counts.PENDING > 0 && <Button variant="outline" size="sm" onClick={selectNextPending} className="shrink-0 rounded-full">다음 미확인 항목</Button>}
          </> : <div><strong className="text-[var(--product-ink)]">평가 대응 범위</strong> — 현재 화면은 공고 요구 항목과 귀사 제안서를 나란히 확인하기 위한 화면입니다. 배점이나 예상 점수를 만들지 않습니다.</div>}
        </section>
      </div>
    </main>
  );
}
