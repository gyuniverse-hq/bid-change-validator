'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight, FileCheck2, LoaderCircle, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CachedNoticeMatches } from '@/components/product/cached-notice-matches';
import { listCompanies, type CompanyProfile } from '@/lib/qualification-api';
import { productProfileCoverage } from '@/lib/product-profile';
import { BUSINESS_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import { getNoticeCatalog } from '@/lib/qualification-state-api';
import { catalogSearch, historicalLabel, presentQualificationState, STATE_TONE_CLASS, type CatalogNotice, type NoticeCatalog, type StatusBucket } from '@/lib/qualification-state';
import { openReviewTarget } from '@/lib/notice-review-target';

const PAGE_SIZE = 20;
const FILTERS: Array<[StatusBucket | 'all', string]> = [['all', '전체'], ['eligible', '저장 판정: 응찰 가능'], ['insufficient_data', '확인 필요'], ['ineligible', '저장 판정: 자격 미달'], ['unreviewed', '미검토']];

export function NoticeReviewCatalog() {
  const router = useRouter();
  const [companies, setCompanies] = useState<CompanyProfile[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [companyReady, setCompanyReady] = useState(false);
  const [companyError, setCompanyError] = useState('');
  const [companyReload, setCompanyReload] = useState(0);
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [businessType, setBusinessType] = useState('all');
  const [status, setStatus] = useState<StatusBucket | 'all'>('all');
  const [offset, setOffset] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [loaded, setLoaded] = useState<{ key: string; data: NoticeCatalog } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [showRejected, setShowRejected] = useState(true);
  const generation = useRef(0);
  const actionLock = useRef(false);
  const company = companies.find((item) => item.id === companyId) ?? null;
  const profile = productProfileCoverage(company);
  const params = { companyId: companyId || undefined, query, businessType: businessType === 'all' ? undefined : businessType,
    status: status === 'all' ? undefined : status, limit: PAGE_SIZE, offset };
  const requestKey = catalogSearch(params);
  const data = loaded?.key === requestKey ? loaded.data : null;

  useEffect(() => {
    let active = true;
    setCompanyReady(false); setCompanyError('');
    void listCompanies().then((items) => {
      if (!active) return;
      setCompanies(items); setCompanyId((previous) => items.some((item) => item.id === previous) ? previous : items[0]?.id ?? '');
      setOffset(0); setCompanyReady(true);
    }).catch((cause) => { if (active) setCompanyError(cause instanceof Error ? cause.message : '회사 정보를 조회하지 못했습니다.'); });
    return () => { active = false; };
  }, [companyReload]);

  useEffect(() => {
    if (!companyReady) return;
    const request = ++generation.current;
    const abort = new AbortController();
    setLoading(true); setError(''); setLoaded(null);
    const currentParams = { companyId: companyId || undefined, query, businessType: businessType === 'all' ? undefined : businessType,
      status: status === 'all' ? undefined : status, limit: PAGE_SIZE, offset };
    void getNoticeCatalog(currentParams, abort.signal).then((value) => {
      if (request !== generation.current) return;
      // 삭제/수집 갱신으로 마지막 페이지가 사라져도 빈 페이지에 갇히지 않는다.
      if (offset > 0 && offset >= value.total) { setOffset(Math.max(0, Math.floor((value.total - 1) / PAGE_SIZE) * PAGE_SIZE)); return; }
      setLoaded({ key: requestKey, data: value });
    }).catch((cause) => { if (request === generation.current) setError(cause instanceof Error ? cause.message : '공고와 판정 상태를 조회하지 못했습니다.'); })
      .finally(() => { if (request === generation.current) setLoading(false); });
    return () => { generation.current += 1; abort.abort(); };
  }, [companyReady, companyId, query, businessType, status, offset, reloadKey, requestKey]);

  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') setReloadKey((value) => value + 1); };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, []);

  async function openReview(notice: CatalogNotice) {
    if (!companyId || actionLock.current) return;
    actionLock.current = true;
    const request = generation.current;
    setBusy(notice.id); setError('');
    try {
      const id = await openReviewTarget({ noticeId: notice.id, bidNoticeNo: notice.bid_notice_no,
        versionNumber: notice.current_version, companyId, caseId: notice.case_id });
      if (request === generation.current) router.push(`/qualification?caseId=${encodeURIComponent(id)}`);
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : '검토 건을 열지 못했습니다.');
    } finally { actionLock.current = false; setBusy(null); }
  }

  function renderRow(notice: CatalogNotice) {
    const view = notice.state ? presentQualificationState(notice.state) : { label: company ? '미검토' : '회사 선택 필요',
      description: '이 회사·현재 차수의 검토 건이 없습니다. 공고 분석의 존재 여부와는 별개입니다.', tone: 'neutral' as const, warnings: [] };
    const historical = notice.state ? historicalLabel(notice.state) : null;
    return <div key={notice.id} className="grid items-center gap-3 border-t border-[var(--product-line-2)] px-5 py-4 lg:grid-cols-[170px_minmax(0,1fr)_160px_72px_105px]">
      <div><span title={view.description} className={`inline-block rounded-full border px-3 py-1 text-xs font-semibold ${STATE_TONE_CLASS[view.tone]}`}>{view.label}</span>
        {notice.state?.stored_reference_date && <span className="mt-1 block text-xs text-[var(--product-muted)]">기준일 {notice.state.stored_reference_date}</span>}</div>
      <div className="min-w-0"><strong className="block text-[15px] font-bold text-[var(--product-ink)]">{notice.title}</strong>
        <p className="mt-1 text-xs text-[var(--product-muted)]">{notice.bid_notice_no} · v{notice.current_version}{notice.current_version > 1 ? ' · 변경 차수' : ''}</p>
        {view.warnings.length > 0 && <details className="mt-2 text-xs text-amber-800"><summary className="cursor-pointer">판정 기준·주의사항 {view.warnings.length}건</summary>{view.warnings.map((warning) => <p className="mt-1" key={warning}>{warning}</p>)}</details>}
        {historical && <p className="mt-1 text-xs text-amber-800">{historical}</p>}</div>
      <span className="text-sm text-[var(--product-muted)]">{notice.institution_name ?? '기관 미상'}</span>
      <span className="text-xs">{labelOf(BUSINESS_TYPE_LABEL, notice.business_type)}</span>
      <Button size="sm" variant="outline" className="rounded-full" onClick={() => void openReview(notice)} disabled={!company || busy !== null || loading}>
        {busy === notice.id ? <LoaderCircle className="animate-spin" /> : null}{notice.case_id ? '검토 열기' : '검토 시작'}<ArrowRight /></Button>
    </div>;
  }

  const active = data?.items.filter((item) => item.status_bucket !== 'ineligible') ?? [];
  const rejected = data?.items.filter((item) => item.status_bucket === 'ineligible') ?? [];
  return <main className="bg-white text-[var(--product-body)]">
    <section className="border-b border-[var(--product-line)] bg-[linear-gradient(120deg,#e6eeff_0%,#f0ebff_48%,#e8f4ff_100%)]">
      <div className="app-shell-container py-9">
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="flex items-center gap-2 text-sm"><CheckCircle2 className="size-4" /><strong>{company ? `${company.name} · 프로필 ${profile.filled}/${profile.total}` : '회사 프로필을 연결해 주세요'}</strong><Link href="/company" className="underline">회사 정보</Link></p>
          {companies.length > 1 && <label className="text-sm">판정 기준 회사 <select aria-label="판정 기준 회사" value={companyId} onChange={(event) => { setCompanyId(event.target.value); setOffset(0); }} disabled={busy !== null} className="ml-2 rounded-lg border bg-white px-3 py-2">{companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}</div>
        {companyError && <p role="alert" className="mt-3 text-rose-700">{companyError} <button className="underline" onClick={() => setCompanyReload((value) => value + 1)}>다시 조회</button></p>}
        <form onSubmit={(event) => { event.preventDefault(); setQuery(draftQuery.trim()); setOffset(0); setReloadKey((value) => value + 1); }} className="mt-4 overflow-hidden rounded-[24px] bg-white shadow-sm">
          <div className="flex flex-col gap-5 p-7 lg:flex-row lg:items-center lg:justify-between"><h1 className="text-[28px] font-extrabold tracking-[-0.04em]">검토할 공고를 바로 찾기</h1>
            <div className="flex w-full items-center gap-2 rounded-2xl border px-4 lg:max-w-[520px]"><Input value={draftQuery} maxLength={200} onChange={(event) => setDraftQuery(event.target.value)} placeholder="공고번호·공고명·기관" aria-label="공고 검색" className="h-14 border-0 shadow-none focus-visible:ring-0" /><button type="submit" aria-label="검색" disabled={!companyReady} className="rounded-full bg-[var(--product-accent)] p-3 text-white"><Search className="size-5" /></button></div></div>
          <div className="flex flex-wrap items-center justify-between gap-2 bg-[var(--product-accent-deep)] px-7 py-4 text-sm text-white"><span className="flex items-center gap-2"><Search className="size-4" /> 공고 찾기 <ChevronRight className="size-4" /><FileCheck2 className="size-4" /> 자격 판정 <ChevronRight className="size-4" /><RefreshCw className="size-4" /> 변경 재검증</span><span className="flex items-center gap-2 text-xs"><ShieldCheck className="size-4" />저장 판정과 분석의 완전성은 구분합니다</span></div>
        </form>
      </div>
    </section>
    {companyReady && <CachedNoticeMatches companyId={companyId || null} />}
    <section className="app-shell-container pb-20 pt-4" aria-label="검색된 공고의 저장 검토 상태">
      <div className="flex items-center justify-between gap-3"><h2 className="text-[28px] font-extrabold">조회된 공고</h2><Button variant="outline" size="sm" disabled={loading || !companyReady} onClick={() => setReloadKey((value) => value + 1)}><RefreshCw /> 새로 조회</Button></div>
      <p className="mt-2 text-sm text-[var(--product-muted)]">집계는 검색어·선택 사업 유형에 해당하는 전체 공고 기준입니다. 확인 필요에는 재판정·분석 실패·자료 확인이 포함됩니다.</p>
      <div className="mt-5 grid grid-cols-2 overflow-hidden rounded-[18px] border sm:grid-cols-3 lg:grid-cols-5">{FILTERS.map(([key, label]) => <button type="button" key={key} aria-pressed={status === key} disabled={!companyReady || busy !== null || (!company && key !== 'all')} onClick={() => { setStatus(key); setOffset(0); }} className={`border-r px-3 py-4 text-center ${status === key ? 'bg-[var(--product-tint)]' : ''}`}><span className="block text-xs">{label}</span><strong className="mt-1 block text-xl">{loading || !data ? '—' : (key === 'all' ? data.scope_total : data.status_counts[key]).toLocaleString()}</strong></button>)}</div>
      <div className="mt-4 flex flex-wrap items-center gap-2"><span className="text-xs font-bold">사업 유형</span>{[['all', '전체'], ...['SERVICE', 'GOODS', 'CONSTRUCTION', 'FOREIGN'].map((key) => [key, labelOf(BUSINESS_TYPE_LABEL, key)])].map(([key, label]) => <button type="button" key={key} aria-pressed={businessType === key} disabled={busy !== null} onClick={() => { setBusinessType(key); setOffset(0); }} className={`rounded-full border px-3 py-1.5 text-xs ${businessType === key ? 'bg-[var(--product-tint)] font-bold' : ''}`}>{label} {data ? (key === 'all' ? data.query_total : data.business_counts[key] ?? 0).toLocaleString() : '—'}</button>)}</div>
      {error && <div role="alert" className="mt-5 flex items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><AlertCircle className="size-4 shrink-0" />{error}<button className="shrink-0 underline" onClick={() => setReloadKey((value) => value + 1)}>다시 조회</button></div>}
      {loading || !companyReady ? !companyError && <p role="status" className="my-12 flex items-center justify-center gap-2"><LoaderCircle className="size-5 animate-spin" />공고와 저장 판정 상태를 조회하고 있습니다.</p> : data && <>
        <p className="mt-4 text-xs text-[var(--product-muted)]">조건에 맞는 공고 {data.total.toLocaleString()}건 · {data.total ? offset + 1 : 0}–{offset + data.items.length}번째 표시</p>
        {active.length > 0 && <div className="mt-4 overflow-hidden rounded-[20px] border">{active.map(renderRow)}</div>}
        {rejected.length > 0 && <section className="mt-5"><button type="button" onClick={() => setShowRejected((value) => !value)} aria-expanded={showRejected} className="text-sm font-semibold">이 페이지의 저장 판정 자격 미달 {rejected.length}건 · {showRejected ? '접기' : '펼치기'}</button>{showRejected && <div className="mt-3 overflow-hidden rounded-[20px] border">{rejected.map(renderRow)}</div>}</section>}
        {!data.items.length && <p className="my-12 rounded-xl border border-dashed p-8 text-center text-sm">선택한 검색 조건과 저장 상태에 해당하는 공고가 없습니다.</p>}
        <nav aria-label="공고 페이지" className="mt-6 flex items-center justify-center gap-4"><Button variant="outline" disabled={offset === 0 || busy !== null} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}><ChevronLeft /> 이전</Button><span className="text-sm">{Math.floor(offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(data.total / PAGE_SIZE))}</span><Button variant="outline" disabled={offset + PAGE_SIZE >= data.total || busy !== null} onClick={() => setOffset((value) => value + PAGE_SIZE)}>다음 <ChevronRight /></Button></nav>
      </>}
    </section>
  </main>;
}
