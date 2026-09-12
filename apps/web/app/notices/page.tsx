'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Building2,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  FileCheck2,
  FileText,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getNoticeVersions, listNotices, listPreflightCases, type BidNoticeSummary, type PreflightCase } from '@/lib/api';
import {
  createPreflightCaseWithCompany,
  listCompanies,
  type CompanyProfile,
  type QualificationJudgmentSummary,
} from '@/lib/qualification-api';
import { loadCurrentJudgment } from '@/lib/case-workspace';
import { productProfileCoverage } from '@/lib/product-profile';
import { ASK_BACK_REASON_COPY, BUSINESS_TYPE_LABEL, labelOf } from '@/lib/status-copy';
type OverallStatus = QualificationJudgmentSummary['overall_status'] | 'unreviewed';
type StatusFilter = 'all' | OverallStatus;
type CaseStatusMeta = { caseItem: PreflightCase; judgment: QualificationJudgmentSummary | null };
type QuickTile = { label: string; value: string | number; icon: LucideIcon; filter: StatusFilter };

const STATUS_COPY: Record<OverallStatus, { label: string; className: string }> = {
  eligible: { label: '응찰 가능', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  insufficient_data: { label: '확인 필요', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  ineligible: { label: '자격 미달', className: 'border-rose-200 bg-rose-50 text-rose-700' },
  unreviewed: { label: '미검토', className: 'border-slate-200 bg-slate-50 text-slate-600' },
};

export default function NoticesPage() {
  const router = useRouter();
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [noticeTotal, setNoticeTotal] = useState(0);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [caseMeta, setCaseMeta] = useState<Record<string, CaseStatusMeta>>({});
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [loading, setLoading] = useState(true);
  const [creatingNoticeId, setCreatingNoticeId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [showRejected, setShowRejected] = useState(true);

  async function hydrateCaseMeta(caseItems: PreflightCase[], noticeItems: BidNoticeSummary[], selectedCompanyId: string) {
    const pairs = await Promise.all(
      caseItems.filter((item, index) => item.company_id === selectedCompanyId
        && noticeItems.some((notice) => notice.id === item.notice_id && notice.current_version === item.current_version_number)
        && caseItems.findIndex((other) => other.notice_id === item.notice_id && other.company_id === selectedCompanyId && other.current_version_number === item.current_version_number) === index
      ).map(async (caseItem) => {
        try {
          const run = await loadCurrentJudgment(caseItem);
          const judgment = run ? { ...run, judgment_count: run.judgments.length, unknown_count: run.judgments.filter((item) => item.status === 'UNKNOWN').length, unsatisfied_count: run.judgments.filter((item) => item.status === 'UNSATISFIED').length } : null;
          return [caseItem.notice_id, { caseItem, judgment }] as const;
        } catch {
          return [caseItem.notice_id, { caseItem, judgment: null }] as const;
        }
      }),
    );
    setCaseMeta(Object.fromEntries(pairs));
  }

  async function initialize(searchQuery = '') {
    setLoading(true);
    setError('');
    try {
      const [noticeResult, caseResult, companies] = await Promise.all([
        listNotices(searchQuery),
        listPreflightCases(),
        listCompanies(),
      ]);
      setNotices(noticeResult.items);
      setNoticeTotal(noticeResult.total);
      setCases(caseResult.items);
      setCompany(companies[0] ?? null);
      await hydrateCaseMeta(caseResult.items, noticeResult.items, companies[0]?.id ?? '');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '공고 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  function noticeStatus(noticeId: string): OverallStatus {
    return caseMeta[noticeId]?.judgment?.overall_status ?? 'unreviewed';
  }

  const filteredNotices = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return notices.filter((notice) => {
      const matchesText =
        !normalized ||
        notice.title.toLowerCase().includes(normalized) ||
        notice.bid_notice_no.toLowerCase().includes(normalized) ||
        (notice.announcing_institution_name ?? '').toLowerCase().includes(normalized);
      const status = caseMeta[notice.id]?.judgment?.overall_status ?? 'unreviewed';
      return matchesText && (statusFilter === 'all' || status === statusFilter);
    });
  }, [notices, query, statusFilter, caseMeta]);

  const activeNotices = filteredNotices.filter((notice) => noticeStatus(notice.id) !== 'ineligible');
  const rejectedNotices = filteredNotices.filter((notice) => noticeStatus(notice.id) === 'ineligible');
  const profile = productProfileCoverage(company);
  const missingProfile = profile.missing.map((area) => area.label);
  const profileReady = Boolean(company) && missingProfile.length === 0;

  const counts = useMemo(() => {
    const result = { eligible: 0, insufficient_data: 0, ineligible: 0, unreviewed: 0 };
    notices.forEach((notice) => {
      const status = caseMeta[notice.id]?.judgment?.overall_status ?? 'unreviewed';
      result[status] += 1;
    });
    return result;
  }, [notices, caseMeta]);

  const proposalDocumentCount = cases.reduce((sum, caseItem) => sum + caseItem.documents.length, 0);
  const unknownTotal = Object.values(caseMeta).reduce((sum, item) => sum + (item.judgment?.unknown_count ?? 0), 0);
  const firstUnknownCase = Object.values(caseMeta).find((item) => (item.judgment?.unknown_count ?? 0) > 0)?.caseItem;

  const quickTiles: QuickTile[] = [
    { label: '응찰 가능', value: counts.eligible, icon: CheckCircle2, filter: 'eligible' },
    { label: '확인 필요', value: counts.insufficient_data, icon: CircleHelp, filter: 'insufficient_data' },
    { label: '자격 미달', value: counts.ineligible, icon: XCircle, filter: 'ineligible' },
    { label: '미검토', value: counts.unreviewed, icon: FileCheck2, filter: 'unreviewed' },
    { label: '검색된 공고', value: noticeTotal, icon: FileText, filter: 'all' },
    { label: '준비 문서', value: `${proposalDocumentCount}개`, icon: Building2, filter: 'all' },
  ];

  async function startReview(notice: BidNoticeSummary) {
    const existing = caseMeta[notice.id]?.caseItem;
    if (existing) {
      router.push(`/qualification?caseId=${existing.id}`);
      return;
    }
    if (!company) {
      setError('먼저 사용할 회사 프로필이 필요합니다.');
      return;
    }

    setCreatingNoticeId(notice.id);
    setError('');
    try {
      const versions = await getNoticeVersions(notice.id);
      const current = versions.find((item) => item.is_current) ?? versions[0];
      if (!current) throw new Error('현재 공고 버전을 찾지 못했습니다.');
      const baseline = versions
        .filter((item) => item.version_number < current.version_number)
        .sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({
        notice_id: notice.id,
        company_id: company.id,
        baseline_version_number: baseline?.version_number,
        current_version_number: current.version_number,
        title: `${notice.bid_notice_no} 참가자격 검토`,
      });
      const refreshed = await listPreflightCases();
      setCases(refreshed.items);
      await hydrateCaseMeta(refreshed.items, notices, company.id);
      router.push(`/qualification?caseId=${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setCreatingNoticeId(null);
    }
  }

  return (
    <main className="bg-white text-[var(--product-body)]">
      <section className="border-b border-[var(--product-line)] bg-[linear-gradient(120deg,#e6eeff_0%,#f0ebff_48%,#e8f4ff_100%)]">
        {/* 아래 여백은 6타일 카드가 위로 올라와 걸칠 자리다.
           여백에서 카드가 올라온 만큼(62px)을 뺀 값이 히어로 카드와 타일 사이의 실제 간격이 된다. */}
        <div className="app-shell-container pt-8 pb-[96px] md:pt-[34px] md:pb-[124px]">
          <div className="inline-flex min-h-[50px] items-center gap-3 rounded-2xl border border-white/80 bg-white/80 px-3.5 py-2 shadow-sm backdrop-blur">
            <span className={`grid size-8 place-items-center rounded-full ${profileReady ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{profileReady ? <CheckCircle2 className="size-5" /> : <CircleHelp className="size-5" />}</span>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <strong>{company ? `${company.name} 프로필 ${profile.filled}/${profile.total} 영역 연결` : '회사 프로필이 필요합니다'}</strong>
              <span className="text-[var(--product-muted)]">{profileReady ? '판정에 필요한 기본 정보가 준비됐습니다' : `${missingProfile.slice(0, 2).join(' · ')}${missingProfile.length > 2 ? ` 외 ${missingProfile.length - 2}개` : ''} 비어 있음 · 채우면 걸러드립니다`}</span>
              {!profileReady && <Link href="/company" className="font-semibold text-[var(--product-accent-deep)]">채우러 가기 →</Link>}
            </div>
          </div>

          <div className="mt-[22px] grid gap-[22px] lg:grid-cols-[372px_minmax(0,1fr)]">
            <form onSubmit={(event) => { event.preventDefault(); void initialize(query); }} className="rounded-[24px] bg-white p-7 shadow-[0_16px_48px_rgba(55,70,120,0.12)]">
              <h1 className="text-[31px] font-extrabold leading-[1.35] tracking-[-0.04em] text-[var(--product-ink)]">검토할 공고를<br />바로 찾기</h1>
              <p className="mt-3 text-[14px] leading-6 text-[var(--product-muted)]">실제 수집 공고를 조회하고, 검토를 시작한 공고에는 회사 프로필 기준 판정 상태를 함께 표시합니다.</p>
              <div className="mt-7 flex h-[52px] items-center rounded-2xl border border-[var(--product-line)] bg-white px-4 focus-within:border-[var(--product-accent)]">
                <Input value={query} onChange={(event) => setQuery(event.target.value)} className="h-auto flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" placeholder="공고번호 또는 공고명" aria-label="공고 검색" />
                <button type="submit" className="grid size-10 place-items-center rounded-full bg-[var(--product-accent)] text-white" aria-label="검색">{loading ? <LoaderCircle className="size-5 animate-spin" /> : <Search className="size-5" />}</button>
              </div>
            </form>

            <div className="relative overflow-hidden rounded-[24px] bg-[var(--product-accent-deep)] p-8 text-white shadow-[0_16px_48px_rgba(31,58,176,0.2)]">
              <div className="relative z-10 max-w-3xl">
                <Badge className="border-white/20 bg-white/10 text-white">근거 우선</Badge>
                <h2 className="mt-4 text-[34px] font-extrabold leading-[1.3] tracking-[-0.035em]">근거가 붙은 공고만<br />판정으로 이어갑니다</h2>
                <p className="mt-4 max-w-2xl text-[15px] leading-7 text-white/80">공고 원문에서 구조화된 자격조건과 회사 프로필을 비교합니다. 근거가 없거나 정보가 부족하면 억지로 결론 내리지 않고 확인 필요로 남깁니다.</p>
              </div>
              <ShieldCheck className="absolute -right-10 -bottom-16 size-64 text-white/[0.07]" strokeWidth={1} />
            </div>
          </div>
        </div>

      </section>

      {/*
        6타일 카드는 히어로 경계에 걸쳐 보이게 둔다.
        이전에는 transform으로 아래로 밀고(-mb + translate-y) 다음 섹션이 고정 pt로 피하는 구조였는데,
        transform은 레이아웃 높이를 바꾸지 않아 118 - 62 - 62 = -6px 만큼 항상 아래를 덮었다.
        (「공고 조회」 라벨 윗부분이 잘려 보이던 원인)
        이제는 섹션 밖에서 위로 당긴다. 카드의 실제 높이가 아래 내용을 밀어내므로 겹칠 수 없다.
      */}
      <div className="app-shell-container relative z-10 -mt-[62px]">
          <div className="grid overflow-hidden rounded-[22px] border border-[var(--product-line)] bg-white shadow-[0_18px_46px_rgba(35,50,90,0.1)] sm:grid-cols-2 lg:grid-cols-6">
            {quickTiles.map(({ label, value, icon: Icon, filter }) => (
              <button key={label} type="button" onClick={() => setStatusFilter(filter)} className={`min-h-[124px] border-b border-r border-[var(--product-line)] px-4 py-5 text-center transition-colors hover:bg-[var(--product-tint)] lg:border-b-0 ${statusFilter === filter ? 'bg-[#f4f6ff]' : ''}`}>
                <Icon className="mx-auto size-6 text-[var(--product-accent)]" />
                <span className="mt-2 block text-[13px] font-medium text-[var(--product-muted)]">{label}</span>
                <strong className="mt-1 block text-[24px] leading-8 text-[var(--product-ink)]">{value}</strong>
              </button>
            ))}
          </div>
      </div>

      <div className="app-shell-container pb-20 pt-14">
        {/* 실패를 알리기만 하면 사용자가 할 수 있는 일이 없다. 같은 조회를 바로 다시 걸 수 있게 둔다. */}
        {error && <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-start gap-2"><AlertCircle className="mt-0.5 size-4 shrink-0" />{error}</span>
          <Button type="button" variant="outline" size="sm" className="shrink-0 rounded-full border-rose-300 bg-white text-rose-700 hover:bg-rose-100" disabled={loading} onClick={() => void initialize(query)}>
            {loading ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} 다시 시도
          </Button>
        </div>}

        <section>
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <p className="text-[13px] font-semibold text-[var(--product-accent-deep)]">공고 조회</p>
              <h2 className="mt-1 text-[34px] font-extrabold tracking-[-0.04em] text-[var(--product-ink)]">조회된 공고</h2>
              <p className="mt-2 text-[14px] text-[var(--product-muted)]">실제 API에서 조회된 공고입니다. 아직 자동 매칭 전이며, 저장된 판정이 있으면 최신 결과를 함께 표시합니다.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {(['all', 'eligible', 'insufficient_data', 'unreviewed'] as StatusFilter[]).map((filter) => <button key={filter} type="button" onClick={() => setStatusFilter(filter)} className={`rounded-full border px-4 py-2 text-[13px] font-medium ${statusFilter === filter ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>{filter === 'all' ? '전체' : STATUS_COPY[filter].label}</button>)}
            </div>
          </div>

          {!loading && activeNotices.length > 6 && <p className="mt-3 text-[13px] text-[var(--product-muted)]">현재 불러온 {activeNotices.length}건 중 6건 표시 · 원하는 공고는 검색으로 좁혀보세요</p>}

          {loading ? <div className="grid min-h-64 place-items-center"><LoaderCircle className="size-7 animate-spin text-[var(--product-accent)]" /></div> : activeNotices.length ? (
            <div className="mt-7 grid gap-[18px] lg:grid-cols-3">
              {activeNotices.slice(0, 6).map((notice) => {
                const status = noticeStatus(notice.id);
                const meta = caseMeta[notice.id];
                return <article key={notice.id} className="flex min-h-[286px] flex-col rounded-[20px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_30px_rgba(35,50,90,0.06)] transition-transform hover:-translate-y-1">
                  <div className="flex items-center justify-between gap-3"><span className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${STATUS_COPY[status].className}`}>{STATUS_COPY[status].label}</span><span className="text-[12px] text-[var(--product-faint)]">현재 v{notice.current_version}</span></div>
                  <h3 className="mt-5 line-clamp-3 text-[21px] font-bold leading-8 tracking-[-0.025em] text-[var(--product-ink)]">{notice.title}</h3>
                  <p className="mt-3 text-[13px] leading-6 text-[var(--product-muted)]">{notice.announcing_institution_name ?? '공고기관 미상'} · {labelOf(BUSINESS_TYPE_LABEL, notice.business_type)}</p>
                  {meta?.judgment && <p className="mt-2 text-[13px] text-[var(--product-muted)]">판정 {meta.judgment.judgment_count}건 · 확인 필요 {meta.judgment.unknown_count}건 · 미달 {meta.judgment.unsatisfied_count}건</p>}
                  <div className="mt-auto flex items-end justify-between gap-3 pt-5"><div><span className="block text-[11px] text-[var(--product-faint)]">공고번호</span><strong className="mt-1 block text-[12px] font-semibold">{notice.bid_notice_no}</strong></div><Button size="sm" onClick={() => void startReview(notice)} disabled={creatingNoticeId !== null} className="rounded-full px-4">{creatingNoticeId === notice.id ? <LoaderCircle className="animate-spin" /> : meta ? '검토 보기' : '검토 시작'}<ArrowRight /></Button></div>
                </article>;
              })}
            </div>
          ) : <div className="mt-7 rounded-[20px] border border-dashed border-[var(--product-line)] bg-[var(--product-tint)] px-6 py-16 text-center"><Search className="mx-auto size-8 text-[var(--product-faint)]" /><p className="mt-3 font-semibold">조회된 공고가 없습니다.</p><p className="mt-1 text-sm text-[var(--product-muted)]">검색어나 판정 상태 필터를 바꿔보세요.</p></div>}
        </section>

        <section className="mt-12 overflow-hidden rounded-[22px] border border-[var(--product-line)] bg-[var(--product-tint)]">
          <button type="button" onClick={() => setShowRejected((value) => !value)} className="flex w-full items-center gap-4 px-6 py-5 text-left"><ChevronDown className={`size-5 transition-transform ${showRejected ? 'rotate-180' : ''}`} /><div className="flex-1"><h3 className="text-[18px] font-bold text-[var(--product-ink)]">자격 미달로 접어둔 공고 {rejectedNotices.length}건</h3><p className="mt-1 text-[13px] text-[var(--product-muted)]">숨기지 않습니다. 조건이나 회사 정보가 바뀌면 다시 검토할 수 있습니다.</p></div><span className="text-[13px] font-medium">{showRejected ? '접기' : '펼치기'}</span></button>
          {showRejected && <div className="border-t border-[var(--product-line)] bg-white px-6">{rejectedNotices.length ? rejectedNotices.map((notice) => {
            const meta = caseMeta[notice.id];
            return <div key={notice.id} className="flex flex-col gap-3 border-b border-[var(--product-line-2)] py-5 last:border-b-0 md:flex-row md:items-center"><span className={`w-fit rounded-full border px-3 py-1 text-[12px] font-semibold ${STATUS_COPY.ineligible.className}`}>자격 미달</span><div className="min-w-0 flex-1"><strong className="block truncate text-[15px]">{notice.title}</strong><span className="mt-1 block text-[12px] text-[var(--product-muted)]">{meta?.judgment ? `미달 ${meta.judgment.unsatisfied_count}건 · 확인 필요 ${meta.judgment.unknown_count}건` : notice.bid_notice_no}</span></div><button type="button" onClick={() => void startReview(notice)} className="text-left text-[13px] font-semibold text-[var(--product-accent-deep)]">근거 확인 →</button></div>;
          }) : <p className="py-8 text-center text-sm text-[var(--product-muted)]">현재 자격 미달로 판정된 공고가 없습니다.</p>}</div>}
        </section>

        <section className="mt-12 grid gap-5 lg:grid-cols-[minmax(0,1fr)_452px]">
          <div className="rounded-[22px] border border-[var(--product-line)] bg-white p-7"><div className="flex items-center gap-3"><h2 className="text-[27px] font-extrabold tracking-[-0.035em]">공지사항</h2><Sparkles className="size-5 text-[var(--product-accent)]" /></div><div className="mt-5 divide-y divide-[var(--product-line-2)]">{[['데이터 연결', '공고·회사·판정 데이터를 실제 나라장터 수집 기준으로 연결합니다.'], ['근거 원칙', '판정 결과는 공고 원문 근거와 연결되는 경우에만 화면에 보여줍니다.'], ['변경공고', '변경공고는 이전 차수를 덮어쓰지 않고 판정 영향과 함께 추적합니다.']].map(([title, text]) => <div key={title} className="grid gap-2 py-5 sm:grid-cols-[130px_minmax(0,1fr)]"><strong className="text-[13px] text-[var(--product-accent-deep)]">{title}</strong><span className="text-[14px]">{text}</span></div>)}</div></div>
          <aside className="rounded-[22px] bg-[var(--product-accent-deep)] p-7 text-white"><div className="flex items-start justify-between gap-3"><div><p className="text-[12px] font-semibold text-white/65">확인 필요</p><h2 className="mt-1 text-[26px] font-extrabold">확인이 필요한 항목</h2></div><strong className="text-[34px]">{unknownTotal}</strong></div><p className="mt-3 text-[14px] leading-6 text-white/75">정보가 부족한 항목은 미달로 만들지 않고 확인 필요로 남깁니다.</p><div className="mt-6 space-y-3">{Object.entries(ASK_BACK_REASON_COPY).map(([key, reason]) => <div key={key} className="rounded-2xl bg-white/10 p-4"><span className="flex items-center gap-2 text-[14px] font-semibold">{reason.canAnswer ? <CircleHelp className="size-4" /> : <ShieldCheck className="size-4" />} {reason.label}</span><p className="mt-2 text-[12px] leading-5 text-white/65">{reason.description}</p></div>)}</div>{firstUnknownCase ? <Link href={`/ask-back?caseId=${firstUnknownCase.id}`} className="mt-6 inline-flex items-center gap-2 text-[13px] font-bold">확인 필요 항목 보기 <ArrowRight className="size-4" /></Link> : <p className="mt-6 text-[13px] text-white/65">지금 답할 항목이 없습니다</p>}</aside>        </section>

        <section className="mt-12 flex flex-col justify-between gap-5 rounded-[24px] border border-[#d9ddf8] bg-[#f2f4ff] px-8 py-7 md:flex-row md:items-center"><div><h2 className="text-[25px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">채우면 판정이 더 정확해집니다</h2><p className="mt-2 text-[14px] text-[var(--product-muted)]">{missingProfile.length ? `${missingProfile.join(' · ')} 영역이 아직 비어 있습니다.` : '현재 기본 프로필 영역이 모두 연결되어 있습니다.'}</p></div><div className="flex items-center gap-4"><span className="text-[13px] font-semibold">{profile.total}개 영역 중 {profile.filled}개 연결</span><Link href="/company"><Button variant="outline" className="rounded-full border-[var(--product-accent)] bg-white text-[var(--product-accent-deep)]">프로필 보완</Button></Link></div></section>
      </div>
    </main>
  );
}
