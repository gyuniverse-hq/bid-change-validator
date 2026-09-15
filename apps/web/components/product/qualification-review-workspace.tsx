'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, FileSearch, GitCompareArrows, LoaderCircle, Play, RefreshCw } from 'lucide-react';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { currentRevalidation, isLocked } from '@/lib/copilot-actions';
import { CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import { QualificationRow } from '@/components/product/qualification-row';
import { QualificationSourceOverview } from '@/components/product/qualification-source-overview';
import { QualificationStateSummary } from '@/components/product/qualification-state-summary';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { getNotice, listNotices, listPreflightCases, type BidNoticeDetail, type BidNoticeSummary, type PreflightCase } from '@/lib/api';
import { listCompanies, type CompanyProfile, type ExtractionStrategy } from '@/lib/qualification-api';
import { openReviewTarget } from '@/lib/notice-review-target';
import { ANALYSIS_STATUS_COPY, DROPPED_REASON_LABEL, REQUIREMENT_TYPE_LABEL, analysisStatusLabel, labelOf } from '@/lib/status-copy';
import {
  canRejudge, canRevalidateDetail, createDetailRequestGate,
  type QualificationDetail, type ReviewMode, type ReviewOutcome, type ReviewStage,
} from '@/lib/qualification-detail';
import { loadCurrentQualificationDetail, runCurrentQualificationReview, getAnalysisOptions } from '@/lib/qualification-detail-api';
import { qualificationDetailView, recordedComparison } from '@/lib/qualification-detail-view';

const STAGE_COPY: Record<ReviewStage, string> = {
  checking: '현재 공고·회사·분석 기준을 확인하고 있습니다.',
  analysis: '공고 원문 분석을 실행하고 있습니다.',
  judgment: '회사 정보와 요건을 비교해 판정을 저장하고 있습니다.',
  refresh: '저장 후 현재 상태·판정·근거를 다시 조회하고 있습니다.',
};

export function QualificationReviewWorkspace({ caseId }: { caseId: string | null }) {
  return caseId ? <ExistingQualification key={caseId} caseId={caseId} /> : <QualificationStarter />;
}

function ExistingQualification({ caseId }: { caseId: string }) {
  const router = useRouter();
  const { controller, action } = useActions(caseId);
  const [detail, setDetail] = useState<QualificationDetail | null>(null);
  const [notice, setNotice] = useState<BidNoticeDetail | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [contextWarning, setContextWarning] = useState('');
  const [busy, setBusy] = useState<'load' | 'write' | null>('load');
  const [stage, setStage] = useState<ReviewStage>('checking');
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState<ReviewOutcome | null>(null);
  const [mustRefresh, setMustRefresh] = useState(false);
  const [evidenceKey, setEvidenceKey] = useState<string | null>(null);
  const gate = useRef(createDetailRequestGate());
  const operation = useRef(false);
  const lastAction = useRef('');
  const [strategy, setStrategy] = useState<ExtractionStrategy | undefined>();
  const [reviewEnabled, setReviewEnabled] = useState(false);
  const [optionsWarning, setOptionsWarning] = useState('');
  const selectedStrategy = strategy ?? detail?.analysis?.extraction_strategy ?? 'legacy';
  const analysisDisabled = selectedStrategy === 'review_v1' && !reviewEnabled;

  const load = useCallback(async () => {
    // 읽기가 쓰기 작업의 후속 처리를 취소하지 않도록 한다. 쓰기 종료 후에는 반드시 읽는다.
    if (operation.current) return;
    const ticket = gate.current.begin();
    setBusy('load'); setError(''); setDetail(null); setEvidenceKey(null);
    setNotice(null); setCompany(null); setCases([]); setContextWarning('');
    try {
      const value = await loadCurrentQualificationDetail(caseId, ticket.signal);
      if (!ticket.isCurrent()) return;
      setDetail(value); setMustRefresh(false); setBusy(null);
      // 제목/회사 표시와 이동 목록은 판정 기준이 아니다. 부가 조회 실패로 현재 판정을 지우지 않는다.
      const extra = await Promise.allSettled([
        getNotice(value.caseItem.notice_id), listCompanies(),
        value.caseItem.company_id ? listPreflightCases(value.caseItem.company_id) : Promise.resolve({ items: [] as PreflightCase[] }),
      ]);
      if (!ticket.isCurrent()) return;
      if (extra[0].status === 'fulfilled' && extra[0].value.id === value.caseItem.notice_id) setNotice(extra[0].value);
      if (extra[1].status === 'fulfilled') setCompany(extra[1].value.find(x => x.id === value.caseItem.company_id) ?? null);
      if (extra[2].status === 'fulfilled') setCases(extra[2].value.items.filter(x => x.company_id === value.caseItem.company_id));
      if (extra.some(x => x.status === 'rejected')) setContextWarning('일부 공고·회사 표시 정보를 불러오지 못했습니다. 판정은 아래의 저장 기준을 사용합니다.');
    } catch (cause) {
      if (ticket.isCurrent()) {
        setDetail(null); setError(cause instanceof Error ? cause.message : '판정 상태 조회에 실패했습니다.'); setMustRefresh(true);
      }
    } finally { if (ticket.isCurrent()) setBusy(null); }
  }, [caseId]);

  useEffect(() => {
    const abort = new AbortController();
    void getAnalysisOptions(abort.signal).then(options => {
      if (!abort.signal.aborted) setReviewEnabled(options.strategies.some(x => x.id === 'review_v1' && x.enabled));
    }).catch(() => {
      if (!abort.signal.aborted) setOptionsWarning('새 분석 경로의 활성화 상태를 확인하지 못했습니다. 기존 조회와 회사 재판정은 사용할 수 있습니다.');
    });
    return () => abort.abort();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => { window.clearTimeout(timer); gate.current.cancel(); };
  }, [load]);
  useEffect(() => {
    // 다른 탭의 회사 수정/답변 입력 후 복귀 시 재조회한다. 자동 분석/판정은 하지 않는다.
    const refresh = () => { if (document.visibilityState === 'visible' && !operation.current) void load(); };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [load]);
  useEffect(() => {
    const id = action.result?.result_judgment_run_id;
    const stamp = `${action.revision}:${action.stage}:${id ?? ''}`;
    if (['COMPLETED', 'DONE_REFRESH_FAILED', 'OUTCOME_UNKNOWN', 'STALE'].includes(action.stage) && stamp !== lastAction.current) {
      lastAction.current = stamp;
      if (!operation.current) void load();
    }
  }, [action.stage, action.revision, action.result?.result_judgment_run_id, load]);

  async function run(mode: ReviewMode) {
    if (!detail || busy !== null || mustRefresh || operation.current || isLocked(controller.get(caseId))) return;
    if (mode !== 'rejudge' && analysisDisabled) return;
    if (!controller.acquireReview(caseId)) return;
    operation.current = true;
    const ticket = gate.current.begin();
    const previous = detail;
    setBusy('write'); setDetail(null); setEvidenceKey(null); setFeedback(null); setError('');
    try {
      const outcome = await runCurrentQualificationReview(previous, mode, step => {
        if (ticket.isCurrent()) setStage(step);
      }, ticket.signal, mode === 'rejudge' ? undefined : selectedStrategy);
      if (!ticket.isCurrent() || outcome.status === 'ABANDONED') return;
      setFeedback(outcome); setDetail(outcome.detail);
      setMustRefresh(outcome.status !== 'COMPLETE');
    } catch (cause) {
      if (ticket.isCurrent()) {
        setError(cause instanceof Error ? cause.message : '검토 기준을 확인하지 못했습니다. 상태를 다시 조회해 주세요.');
        setDetail(null); setMustRefresh(true);
      }
    } finally {
      operation.current = false; controller.releaseReview(caseId);
      if (ticket.isCurrent()) setBusy(null);
    }
  }

  const source = detail?.baseline.judgment ?? null;
  const revalidation = currentRevalidation(action.result, {
    caseId, baselineAnalysisId: detail?.baseline.analysis?.id,
    currentAnalysisId: detail?.analysis?.id, judgmentId: detail?.judgment?.id,
  });
  const selectedEvidence = detail?.analysis?.evidence.find(x => x.evidence_key === evidenceKey) ?? null;
  const locked = busy !== null || isLocked(action) || mustRefresh;
  const analysis = detail?.analysis ?? null;
  const view = detail ? qualificationDetailView(detail) : null;
  const facts = analysis?.diagnostics.filter(x => x.kind === 'NOTICE_FACT') ?? [];
  const pipeline = analysis?.diagnostics.filter(x => x.kind !== 'NOTICE_FACT') ?? [];
  const dropped = analysis?.dropped_requirements ?? [];
  const askable = new Set(detail?.questions.filter(x => x.askable).map(x => x.requirement_key) ?? []);

  return <main className="bg-white text-[var(--product-body)]"><div className="app-shell-container py-10">
    {feedback && <section role="status" className="mb-5 rounded-[14px] border border-slate-200 bg-slate-50 p-4 text-sm">
      <p>{feedback.message}</p>
      {feedback.receipts.length > 0 && <details className="mt-2"><summary className="cursor-pointer">응답으로 확인한 저장 기록 {feedback.receipts.length}건</summary>
        {feedback.receipts.map(x => <p key={`${x.kind}:${x.id}`} className="mt-1 break-all">{x.kind === 'analysis' ? '분석' : '판정'} · v{x.version_number} · {x.id}</p>)}
      </details>}
    </section>}
    {error && <p role="alert" className="mb-5 flex gap-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-700"><AlertCircle className="size-5 shrink-0" />{error}</p>}
    {!detail ? <section className="rounded-[20px] border p-6">
      {busy ? <p role="status" className="flex gap-2"><LoaderCircle className="size-5 animate-spin" />{busy === 'write' ? STAGE_COPY[stage] : '현재 상태와 연결된 분석·판정·근거를 조회하고 있습니다.'}</p>
        : <><h1 className="text-xl font-bold">현재 판정 상태를 확인해야 합니다</h1><p className="mt-2">조회 실패를 미검토나 0건으로 표시하지 않습니다. 이전 결과를 현재 결과로 대신 사용하지 않습니다.</p></>}
      <div className="mt-4 flex flex-wrap gap-2"><Button variant="outline" disabled={busy !== null} onClick={() => void load()}><RefreshCw />화면 상태만 다시 조회</Button><Link href="/notices" className="self-center underline">공고 목록</Link></div>
    </section> : <>
      <section className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
        <div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge variant="outline">검토 v{detail.caseItem.current_version_number}</Badge>{detail.baseline.version && <Badge variant="secondary">기준 v{detail.baseline.version.version_number}</Badge>}</div>
          <h1 className="mt-4 text-[28px] font-extrabold leading-10">{notice?.title ?? detail.caseItem.notice_title}</h1>
          <p className="mt-2 text-[15px] text-[var(--product-muted)]">공고번호 {detail.caseItem.bid_notice_no} · {notice?.announcing_institution_name ?? notice?.demanding_institution_name ?? '공고기관 표시 정보 미확인'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect aria-label="다른 검토 건으로 이동" className="w-full sm:w-[300px]" value={caseId} disabled={busy !== null} onChange={event => router.push(`/qualification?caseId=${encodeURIComponent(event.target.value)}`)}>
            {(!cases.some(x => x.id === caseId) ? [detail.caseItem, ...cases] : cases).map(x => <NativeSelectOption key={x.id} value={x.id}>{x.bid_notice_no} · {x.title}</NativeSelectOption>)}
          </NativeSelect>
          <Button variant="outline" disabled={busy !== null} onClick={() => void load()}><RefreshCw />상태 다시 조회</Button><Link href="/notices" className="text-sm underline">공고 목록</Link>
        </div>
      </section>
      <CaseTabs caseId={caseId} active="qualification" />
      <section aria-label="분석 경로 선택" className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <label htmlFor="qualification-extraction-strategy" className="text-sm font-semibold">새 분석에 사용할 방식</label>
        <NativeSelect id="qualification-extraction-strategy" value={selectedStrategy} disabled={locked}
          onChange={event => setStrategy(event.target.value as ExtractionStrategy)} className="mt-2 w-full sm:w-[340px]">
          <NativeSelectOption value="legacy">기존 분석 (legacy)</NativeSelectOption>
          <NativeSelectOption value="review_v1" disabled={!reviewEnabled}>조항별 누락 검토 (review_v1){!reviewEnabled ? ' · 서버 비활성' : ''}</NativeSelectOption>
        </NativeSelect>
        <p className="mt-2 text-sm">저장된 분석 방식: {analysis?.extraction_strategy ?? '과거 기록 · 미확인'}. 회사 재판정은 이 선택과 무관하게 현재 분석을 사용합니다.</p>
        <p className="mt-1 text-sm text-amber-800">새 분석은 API 비용이 발생하고 해당 차수의 최신 분석 기준을 바꿉니다. 조항별 검토는 복합조건 그래프 모드가 아니며, 정확도 향상이 아직 실측으로 확인되지는 않았습니다.</p>
        {optionsWarning && <p role="status" className="mt-2 text-sm text-amber-800">{optionsWarning}</p>}
      </section>
      <div className="mt-6"><QualificationStateSummary detail={detail} action={<div className="flex flex-wrap gap-2">
        {canRejudge(detail) ? <Button disabled={locked} onClick={() => void run('rejudge')}><Play />현재 분석으로 회사 재판정</Button>
          : <Button disabled={locked || analysisDisabled || !detail.caseItem.company_id || detail.state.execution_state === 'RUNNING'} onClick={() => void run('start')}><Play />분석하고 판정</Button>}
        <Button variant="outline" disabled={locked || analysisDisabled || !detail.caseItem.company_id || detail.state.execution_state === 'RUNNING'} onClick={() => void run('reanalyze')}><RefreshCw />현재 차수 다시 분석</Button>
      </div>} /></div>
      <p className="mt-2 text-xs text-[var(--product-muted)]">회사 재판정은 공고 추출을 다시 실행하지 않습니다. 다시 분석은 실제 추출을 새로 실행합니다.</p>
      {[...detail.warnings, contextWarning].filter(Boolean).map((text, i) => <p key={i} role="status" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">{text}</p>)}
      {mustRefresh && <Button className="mt-3" variant="outline" onClick={() => void load()}>쓰기 재실행 없이 상태만 확인</Button>}
      {analysis && analysis.status !== 'SUCCEEDED' && <section className="mt-6 rounded-[18px] border border-amber-200 bg-amber-50 p-5">
        <strong>{analysis.status === 'FAILED' && !detail.currentVersion.documents.length ? '현재 차수에 수집된 첨부 문서가 없습니다' : ANALYSIS_STATUS_COPY[analysis.status].label}</strong>
        <p className="mt-1 text-sm">{analysis.status === 'FAILED' && !detail.currentVersion.documents.length ? '취소공고 또는 수집 누락 여부는 원문에서 확인해야 합니다. 자료가 없다는 이유만으로 응찰 가능으로 판정하지 않습니다.' : ANALYSIS_STATUS_COPY[analysis.status].description}</p>
      </section>}
      <ActionCard caseId={caseId} />
      <section className="mt-10">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-[28px] font-extrabold">참가 자격 조건</h2><p className="mt-1 text-sm text-[var(--product-muted)]">선택된 분석과 저장 판정의 같은 요건·근거만 연결합니다. 필수·선호 여부는 항목별로 구분합니다.</p></div>
          <span className="text-sm">구조화 {analysis && analysis.status !== 'FAILED' ? analysis.requirements.length : '—'}건 · 판정 {detail.judgment?.judgments.length ?? '—'}건</span></div>
        <div className="mt-4 overflow-hidden rounded-[18px] border border-[var(--product-line)]">
          <div className="hidden min-h-[45px] grid-cols-[152px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px] items-center bg-[var(--product-tint)] text-[13px] font-semibold lg:grid">{['판정', '참가 자격 조건', '저장된 비교 근거', '원문 근거', '조치'].map(label => <div key={label} className="px-3">{label}</div>)}</div>
          {analysis?.requirements.length ? analysis.requirements.map(requirement => {
            const judgment = detail.judgment?.judgments.find(x => x.requirement_key === requirement.requirement_key) ?? null;
            const evidence = analysis.evidence.find(x => x.evidence_key === requirement.evidence_keys[0]);
            const role = requirement.requirement_role === 'mandatory' ? '필수' : requirement.requirement_role === 'preferred' ? '선호' : '정보';
            return <QualificationRow key={requirement.requirement_key} status={judgment?.status ?? 'UNJUDGED'} basisType={judgment?.basis_type ?? 'NONE'}
              condition={`[${role}] ${labelOf(REQUIREMENT_TYPE_LABEL, requirement.type)} · ${requirement.raw}`} companyValue={recordedComparison(judgment)}
              evidenceLabel={evidence ? '근거 보기' : '근거 없음'} onEvidence={evidence ? () => setEvidenceKey(evidence.evidence_key) : undefined}
              actionLabel={judgment?.status === 'UNKNOWN' ? askable.has(requirement.requirement_key) ? '확인하기' : '원문 확인' : judgment ? '저장 판정' : '판정 필요'}
              onAction={judgment?.status === 'UNKNOWN' ? () => { if (askable.has(requirement.requirement_key)) router.push(`/ask-back?caseId=${encodeURIComponent(caseId)}`); else if (evidence) setEvidenceKey(evidence.evidence_key); } : undefined} />;
          }) : <div className="p-10 text-center"><FileSearch className="mx-auto size-8" /><p className="mt-3">{analysis ? '이번 분석에서 판정 가능한 자격요건을 확보하지 못했습니다.' : '현재 표시할 분석 결과가 없습니다.'}</p></div>}
        </div>
      </section>
      {selectedEvidence && <section className="mt-6" aria-label="선택한 원문 근거"><h2 className="mb-3 text-xl font-bold">선택한 분석의 원문 근거</h2><EvidenceQuote quote={selectedEvidence.quote} location={selectedEvidence.location} /></section>}
      <section className="mt-8 rounded-[20px] border border-[var(--product-line)] p-6">
        <h2 className="text-[21px] font-extrabold">변경공고 영향 재검증</h2>
        <p className="mt-2 text-sm">기준 차수의 과거 판정과 현재 선택 판정을 구분합니다. 기준 결과는 현재 판정 요약에 섞지 않습니다.</p>
        <p className="mt-2 text-sm">기준 분석: {detail.baseline.analysis ? analysisStatusLabel(detail.baseline.analysis.status) : '미확보'} · 기준 판정: {source ? '저장 결과 있음' : '미확보'}</p>
        {revalidation && <p className="mt-2 text-sm">다시 판정한 자격요건 {revalidation.revalidated_keys.length}건</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          {detail.baseline.version && <Button variant="outline" disabled={locked || analysisDisabled || !detail.caseItem.company_id} onClick={() => void run('baseline')}>기준 차수 검토 준비</Button>}
          <Button variant="outline" disabled={locked || !canRevalidateDetail(detail)} onClick={() => void controller.propose(caseId, true)}><GitCompareArrows />전체 변경 요건 재검증 제안</Button>
        </div>
      </section>
      <section id="analysis-scope" className="mt-8 rounded-[20px] border border-[var(--product-line)] p-6">
        <h2 className="text-lg font-extrabold">판정에 들어가지 않은 기록 {facts.length + dropped.length}건</h2>
        {!facts.length && !dropped.length ? <p className="mt-2 text-sm">{view?.emptyScope}</p> : <details className="mt-3"><summary className="cursor-pointer text-sm">판정 밖 확인사항·제외 후보 보기</summary>
          {facts.map((item, index) => <div key={`fact:${index}`} className="mt-3 rounded-xl border p-4 text-sm"><strong>공고 확인사항</strong><p>{item.message}</p>
            {item.evidence_keys.map(key => { const evidence = analysis?.evidence.find(x => x.evidence_key === key); return evidence ? <Button key={key} size="sm" variant="outline" className="mt-2" onClick={() => setEvidenceKey(key)}>원문 근거 보기</Button> : null; })}
          </div>)}
          {dropped.map((item, index) => <div key={`drop:${index}`} className="mt-3 rounded-xl border p-4 text-sm"><strong>구조화에서 제외된 후보</strong><p>{item.raw.trim() || '원문 문구를 확보하지 못했습니다.'}</p><p className="mt-1">{labelOf(DROPPED_REASON_LABEL, item.reason_code)}</p></div>)}
        </details>}
      </section>
      <section className="mt-8 rounded-[20px] border border-[var(--product-line)] p-6">
        <h2 className="text-lg font-extrabold">분석 처리와 판정 기준</h2>
        <p className="mt-2 text-sm">연결 회사: {company?.name ?? detail.caseItem.company_id ?? '미연결'} · <Link href="/company" className="underline">회사 정보 확인</Link></p>
        <p className="mt-2 text-sm">분석 실행: {analysis ? analysisStatusLabel(analysis.status) : '결과 없음'} · 분석 범위: {view?.coverage}</p>
        <p className="mt-2 text-sm">판정 표의 비교값은 현재 회사 입력이 아니라 판정 실행에 저장된 근거입니다. 현재 상태 조회가 처리 완료를 의미해도 전체 요건의 정확성을 보증하지 않습니다.</p>
        {pipeline.map((item, index) => <p key={index} className={`mt-2 rounded-xl p-3 text-sm ${item.severity === 'INFO' ? 'bg-slate-50' : 'bg-amber-50'}`}>{item.message}</p>)}
      </section>
      <QualificationSourceOverview caseItem={detail.caseItem} notice={notice} version={detail.currentVersion} />
    </>}
    {/* Copilot의 확인 버튼과 쓰기 잠금은 기존 컴포넌트를 유지한다. 별도 통합 검증 대상이다. */}
    {!detail && <ActionCard caseId={caseId} />}
  </div></main>;
}

function QualificationStarter() {
  const router = useRouter();
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [noticeId, setNoticeId] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const starterGate = useRef(createDetailRequestGate());
  useEffect(() => {
    const ticket = starterGate.current.begin();
    void Promise.all([listNotices(), listCompanies()]).then(async ([result, items]) => {
      if (!ticket.isCurrent()) return;
      setNotices(result.items); setCompanies(items); setNoticeId(result.items[0]?.id ?? ''); setCompanyId(items[0]?.id ?? '');
      if (items[0]) {
        const history = await listPreflightCases(items[0].id);
        const existing = history.items.find(x => x.company_id === items[0].id);
        if (ticket.isCurrent() && existing) router.replace(`/qualification?caseId=${encodeURIComponent(existing.id)}`);
      }
    }).catch(cause => { if (ticket.isCurrent()) setError(cause instanceof Error ? cause.message : '검토 시작 정보를 읽지 못했습니다.'); })
      .finally(() => { if (ticket.isCurrent()) setBusy(false); });
    return () => { starterGate.current.cancel(); };
  }, [router]);
  const selected = useMemo(() => notices.find(x => x.id === noticeId), [notices, noticeId]);
  async function open() {
    if (!selected || !companyId || busy) return;
    const ticket = starterGate.current.begin();
    setBusy(true); setError('');
    try {
      const id = await openReviewTarget({ noticeId: selected.id, bidNoticeNo: selected.bid_notice_no, versionNumber: selected.current_version, companyId });
      if (ticket.isCurrent()) router.push(`/qualification?caseId=${encodeURIComponent(id)}`);
    } catch (cause) { if (ticket.isCurrent()) setError(cause instanceof Error ? cause.message : '검토 건을 열지 못했습니다.'); }
    finally { if (ticket.isCurrent()) setBusy(false); }
  }
  return <main className="app-shell-container py-10"><section className="rounded-[22px] border p-7">
    <h1 className="text-[28px] font-extrabold">새 참가자격 검토</h1>
    <p className="mt-2 text-sm">선택 목록 밖의 공고는 <Link href="/notices" className="underline">공고 검색</Link>에서 찾을 수 있습니다.</p>
    {error && <p role="alert" className="mt-3 text-rose-700">{error}</p>}
    <div className="mt-6 grid gap-4 md:grid-cols-2"><NativeSelect aria-label="회사 선택" value={companyId} disabled={busy} onChange={event => setCompanyId(event.target.value)}>{companies.map(x => <NativeSelectOption key={x.id} value={x.id}>{x.name}</NativeSelectOption>)}</NativeSelect>
      <NativeSelect aria-label="공고 선택" value={noticeId} disabled={busy} onChange={event => setNoticeId(event.target.value)}>{notices.map(x => <NativeSelectOption key={x.id} value={x.id}>{x.bid_notice_no} · {x.title}</NativeSelectOption>)}</NativeSelect></div>
    <Button className="mt-4" disabled={busy || !selected || !companyId} onClick={() => void open()}>{busy ? <LoaderCircle className="animate-spin" /> : <Play />}검토 건 열기</Button>
  </section></main>;
}
