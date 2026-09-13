'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
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

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { findPreflightCasesByNotice, getNoticeVersions, listNotices, listPreflightCases, type BidNoticeSummary, type PreflightCase } from '@/lib/api';
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

/*
  판정 상태는 Case 한 건당 요청 3개를 쓴다 (분석 목록 · 판정 목록 · 판정 상세).
  공용 API는 Supabase 세션 풀러 상한 때문에 DB 커넥션 2개로 제한돼 있어,
  수백 건을 한 번에 던지면 전부 대기열에 걸려 목록이 몇 분씩 멈춘다. 묶어서 보낸다.
*/
const HYDRATE_CONCURRENCY = 6;

/*
  목록에 한 번에 보여줄 공고 수. 카드 6장일 때는 100건을 불러와 6건만 보여줬는데,
  「검색으로 좁혀서 고른다」는 이 화면의 전제와 어긋난다 (DL-007).
  목록형으로 바꾸면서 한 화면에 비교할 수 있는 양으로 올린다.
*/
const VISIBLE_NOTICE_LIMIT = 20;

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
  // 사업 유형은 목록 API가 그대로 주는 값이라 추측이 없다. 용역만 하는 회사에게 물품·공사는 볼 이유가 없다.
  const [businessTypeFilter, setBusinessTypeFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [creatingNoticeId, setCreatingNoticeId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [showRejected, setShowRejected] = useState(true);
  // 판정 상태는 목록보다 늦게 온다. 다 오기 전에 0으로 그리면 「확인했더니 0건」으로 읽힌다.
  const [metaLoading, setMetaLoading] = useState(true);
  const [metaProgress, setMetaProgress] = useState({ done: 0, total: 0 });
  /*
    hydrate는 백그라운드로 돈다. 앞선 검색의 응답이 늦게 도착하면 새 검색 결과에 섞여
    목록에 없는 공고의 판정이 남는다. 검색마다 세대 번호를 올리고, 세대가 바뀌면 버린다.
  */
  const hydrateGeneration = useRef(0);
  /*
    검색도 마찬가지다. 빠르게 두 번 치면 먼저 보낸 목록 응답이 나중에 도착해
    새 검색 결과를 덮을 수 있다. 세대가 지난 응답은 화면에 넣지 않는다. (#131 리뷰 P1)
  */
  const searchGeneration = useRef(0);

  async function hydrateCaseMeta(caseItems: PreflightCase[], noticeItems: BidNoticeSummary[], selectedCompanyId: string) {
    const generation = (hydrateGeneration.current += 1);
    const targets = caseItems.filter((item, index) => item.company_id === selectedCompanyId
      && noticeItems.some((notice) => notice.id === item.notice_id && notice.current_version === item.current_version_number)
      && caseItems.findIndex((other) => other.notice_id === item.notice_id && other.company_id === selectedCompanyId && other.current_version_number === item.current_version_number) === index
    );
    setMetaLoading(true);
    setMetaProgress({ done: 0, total: targets.length });
    let done = 0;
    for (let index = 0; index < targets.length; index += HYDRATE_CONCURRENCY) {
      const chunk = await Promise.all(
        targets.slice(index, index + HYDRATE_CONCURRENCY).map(async (caseItem) => {
          try {
            const run = await loadCurrentJudgment(caseItem);
            const judgment = run ? { ...run, judgment_count: run.judgments.length, unknown_count: run.judgments.filter((item) => item.status === 'UNKNOWN').length, unsatisfied_count: run.judgments.filter((item) => item.status === 'UNSATISFIED').length } : null;
            return [caseItem.notice_id, { caseItem, judgment }] as const;
          } catch {
            return [caseItem.notice_id, { caseItem, judgment: null }] as const;
          }
        }),
      );
      // 이 사이에 새 검색이 시작됐으면 이 응답은 지난 목록의 것이다. 넣지 않고 끝낸다.
      if (generation !== hydrateGeneration.current) return;
      done += chunk.length;
      // 오는 대로 채운다. 전부 모아서 한 번에 넣으면 마지막 한 건이 늦을 때 화면이 계속 비어 있다.
      setCaseMeta((previous) => ({ ...previous, ...(Object.fromEntries(chunk) as Record<string, CaseStatusMeta>) }));
      setMetaProgress({ done, total: targets.length });
    }
    setMetaLoading(false);
  }

  async function initialize(searchQuery = '') {
    const generation = (searchGeneration.current += 1);
    setLoading(true);
    setError('');
    setCaseMeta({});
    /*
      판정 표시도 같이 초기화한다. caseMeta만 비우고 metaLoading을 false로 두면,
      검토 건을 받아오는 동안 KPI가 「—」 대신 0을, 배지가 「판정 확인 중」 대신 「미검토」를 보여준다.
      확인하지 않은 것을 확인해서 0이라고 말하는 셈이다.
    */
    setMetaLoading(true);
    setMetaProgress({ done: 0, total: 0 });
    // 목록을 받아오는 동안 앞선 hydrate가 끝날 수 있다. 여기서 먼저 세대를 올려 그 응답을 버린다.
    hydrateGeneration.current += 1;
    try {
      const [noticeResult, companies] = await Promise.all([listNotices(searchQuery), listCompanies()]);
      // 이 사이에 새 검색이 시작됐으면 이건 지난 검색의 응답이다. 덮어쓰지 않는다.
      if (generation !== searchGeneration.current) return;
      const selectedCompany = companies[0] ?? null;
      setNotices(noticeResult.items);
      setNoticeTotal(noticeResult.total);
      setCompany(selectedCompany);
      // 목록은 여기서 바로 그린다. 검토 건과 판정 상태는 뒤이어 채운다.
      // hydrate를 기다리면 Case 한 건당 요청 2~3개가 나가서 수백 건이 끝날 때까지 스피너가 안 꺼진다.
      setLoading(false);

      /*
        검토 건은 회사를 정한 뒤에 받는다. company_id 없이 받으면 백엔드가 회사로 걸러주지 않아
        (auth_required=false로 띄우면 로그인 사용자가 없다) 다른 회사 Case가 상위 100칸을 나눠 쓰고,
        우리 회사의 기존 검토 건이 목록 밖으로 밀린다. 그러면 이미 검토한 공고가 전부 「검토 시작」으로 보인다.
      */
      const caseResult = await listPreflightCases(selectedCompany?.id);
      if (generation !== searchGeneration.current) return;
      setCases(caseResult.items);
      void hydrateCaseMeta(caseResult.items, noticeResult.items, selectedCompany?.id ?? '');
    } catch (cause) {
      if (generation !== searchGeneration.current) return;
      setError(cause instanceof Error ? cause.message : '공고 데이터를 불러오지 못했습니다.');
      setLoading(false);
      setMetaLoading(false);
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
      const matchesType = businessTypeFilter === 'all' || notice.business_type === businessTypeFilter;
      return matchesText && matchesType && (statusFilter === 'all' || status === statusFilter);
    });
  }, [notices, query, statusFilter, businessTypeFilter, caseMeta]);

  /*
    기존 검토 건 여부는 이미 받아둔 cases에서 찾는다. caseMeta는 판정 상세까지 받은 뒤에야 차므로
    hydrate 중에 caseMeta로 판단하면 기존 건이 있는데도 「검토 시작」이 뜨고, 누르면 Case를 또 만든다.
    caseMeta는 판정 표시 전용으로 남긴다. (#131 리뷰)
    현재 차수(current_version)와 같은 Case만 「기존 건」으로 본다 — 변경공고가 나면 그 차수는 새로 검토한다.
  */
  const existingCaseByNotice = useMemo(() => {
    const map = new Map<string, PreflightCase>();
    if (!company) return map;
    cases.forEach((item) => {
      if (item.company_id !== company.id || map.has(item.notice_id)) return;
      const notice = notices.find((row) => row.id === item.notice_id);
      if (!notice || notice.current_version !== item.current_version_number) return;
      map.set(item.notice_id, item);
    });
    return map;
  }, [cases, notices, company]);

  // 불러온 목록에 실제로 있는 유형만 버튼으로 만든다. 없는 유형을 띄우면 눌러도 0건이 나온다.
  const businessTypeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    notices.forEach((notice) => counts.set(notice.business_type, (counts.get(notice.business_type) ?? 0) + 1));
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [notices]);

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
    { label: '응찰 가능', value: metaLoading ? '—' : counts.eligible, icon: CheckCircle2, filter: 'eligible' },
    { label: '확인 필요', value: metaLoading ? '—' : counts.insufficient_data, icon: CircleHelp, filter: 'insufficient_data' },
    { label: '자격 미달', value: metaLoading ? '—' : counts.ineligible, icon: XCircle, filter: 'ineligible' },
    { label: '미검토', value: metaLoading ? '—' : counts.unreviewed, icon: FileCheck2, filter: 'unreviewed' },
    { label: '검색된 공고', value: noticeTotal, icon: FileText, filter: 'all' },
    { label: '준비 문서', value: `${proposalDocumentCount}개`, icon: Building2, filter: 'all' },
  ];

  async function startReview(notice: BidNoticeSummary) {
    const existing = existingCaseByNotice.get(notice.id);
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
      /*
        목록에 없다고 없는 게 아니다. 목록은 상위 100건까지만 받아오므로
        그 밖에 있는 기존 검토 건을 놓치고 같은 공고로 Case를 또 만들 수 있다.
        만들기 직전에 이 공고만 다시 확인한다. (#131 리뷰)
      */
      const known = await findPreflightCasesByNotice(notice.id, company.id);
      const reusable = known.items.find((item) => item.current_version_number === notice.current_version);
      if (reusable) {
        setCases((previous) => (previous.some((item) => item.id === reusable.id) ? previous : [...previous, reusable]));
        router.push(`/qualification?caseId=${reusable.id}`);
        return;
      }
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
      const refreshed = await listPreflightCases(company.id);
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

          {/*
            업무 시작점은 검색이다. 이전에는 검색 카드(372px) 옆에 소개 배너가 더 크게 붙어
            화면의 주인공이 소개문이었다. 검색을 전체 너비로 올리고, 제품 원칙을 말하는 배너는
            지우지 않고 한 줄로 줄인다 — 「근거 없으면 판정하지 않는다」는 이 제품의 약속이라 뺄 수 없다.
          */}
          <form onSubmit={(event) => { event.preventDefault(); void initialize(query); }} className="mt-[22px] rounded-[24px] bg-white p-7 shadow-[0_16px_48px_rgba(55,70,120,0.12)]">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div className="min-w-0">
                <h1 className="text-[30px] font-extrabold leading-[1.3] tracking-[-0.04em] text-[var(--product-ink)]">검토할 공고를 바로 찾기</h1>
                <p className="mt-2 text-[14px] leading-6 text-[var(--product-muted)]">공고번호나 공고명으로 좁힌 뒤, 검토를 시작하면 회사 프로필 기준 판정 상태가 함께 붙습니다.</p>
              </div>
              <div className="flex h-[56px] w-full items-center rounded-2xl border border-[var(--product-line)] bg-white px-4 focus-within:border-[var(--product-accent)] lg:max-w-[520px]">
                <Input value={query} onChange={(event) => setQuery(event.target.value)} className="h-auto flex-1 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:ring-0" placeholder="공고번호 또는 공고명" aria-label="공고 검색" />
                <button type="submit" className="grid size-10 place-items-center rounded-full bg-[var(--product-accent)] text-white" aria-label="검색">{loading ? <LoaderCircle className="size-5 animate-spin" /> : <Search className="size-5" />}</button>
              </div>
            </div>
          </form>

          <div className="mt-4 flex flex-col gap-2 rounded-2xl bg-[var(--product-accent-deep)] px-5 py-4 text-white sm:flex-row sm:items-center sm:gap-4">
            <span className="flex shrink-0 items-center gap-2 text-[13px] font-bold"><ShieldCheck className="size-4" />근거 우선</span>
            <p className="text-[13px] leading-6 text-white/80">공고 원문에서 구조화된 자격조건과 회사 프로필을 비교합니다. 근거가 없거나 정보가 부족하면 억지로 결론 내리지 않고 확인 필요로 남깁니다.</p>
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
              <p className="mt-2 text-[14px] text-[var(--product-muted)]">나라장터에서 수집한 공고입니다. 검토를 시작하면 판정 상태가 붙습니다. 아래 「회사 기준으로 판정 가능한 공고」는 이 중 분석이 끝난 것만 모은 자리입니다.</p>
            </div>
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-[62px] shrink-0 text-[12px] font-bold text-[var(--product-muted)]">사업 유형</span>
                <button type="button" onClick={() => setBusinessTypeFilter('all')} className={`rounded-full border px-4 py-2 text-[13px] font-medium ${businessTypeFilter === 'all' ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>전체 {notices.length}</button>
                {businessTypeOptions.map(([type, count]) => <button key={type} type="button" onClick={() => setBusinessTypeFilter(type)} className={`rounded-full border px-4 py-2 text-[13px] font-medium ${businessTypeFilter === type ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>{labelOf(BUSINESS_TYPE_LABEL, type)} {count}</button>)}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-[62px] shrink-0 text-[12px] font-bold text-[var(--product-muted)]">검토 상태</span>
                {(['all', 'eligible', 'insufficient_data', 'unreviewed'] as StatusFilter[]).map((filter) => <button key={filter} type="button" onClick={() => setStatusFilter(filter)} className={`rounded-full border px-4 py-2 text-[13px] font-medium ${statusFilter === filter ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>{filter === 'all' ? '전체' : STATUS_COPY[filter].label}</button>)}
              </div>
            </div>
          </div>

          {metaLoading && metaProgress.total > 0 && <p className="mt-3 flex items-center gap-2 text-[13px] text-[var(--product-muted)]"><LoaderCircle className="size-4 animate-spin" />판정 상태를 불러오는 중입니다 · {metaProgress.done}/{metaProgress.total}건</p>}
          {/* DL-007 — 「전체 공고」가 아니라 「검색으로 좁힌 결과의 상위 N건」이라는 사실을 화면이 말한다. */}
          {!loading && <p className="mt-3 text-[13px] text-[var(--product-muted)]">검색 결과 {noticeTotal.toLocaleString()}건 중 상위 {notices.length}건을 불러왔습니다{businessTypeFilter !== 'all' || statusFilter !== 'all' ? ` · 필터에 맞는 ${activeNotices.length}건` : ''} · 이 중 {Math.min(activeNotices.length, VISIBLE_NOTICE_LIMIT)}건 표시{activeNotices.length > VISIBLE_NOTICE_LIMIT ? ' · 원하는 공고는 검색으로 좁혀보세요' : ''}</p>}

          {loading ? <div className="grid min-h-64 place-items-center"><LoaderCircle className="size-7 animate-spin text-[var(--product-accent)]" /></div> : activeNotices.length ? (
            /*
              카드 6장을 나열하면 한 화면에 6건뿐이라 서로 비교가 안 된다.
              같은 열을 세로로 세워 공고명·기관·유형·변경·검토 상태를 한눈에 견주게 한다.
              마감일 열은 목록 API(BidNoticeSummary)에 bid_closed_at이 없어 넣지 못했다.
              공고마다 버전을 따로 부르면 방금 없앤 N+1이 되살아난다 — 백엔드에 필드 추가를 요청해둔다.
            */
            <div className="mt-6 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
              <div className="hidden grid-cols-[132px_minmax(0,1fr)_180px_96px_112px_128px] items-center gap-3 bg-[var(--product-tint)] px-5 py-3 text-[12px] font-bold text-[var(--product-muted)] lg:grid">
                <span>검토 상태</span><span>공고명 · 공고번호</span><span>공고기관</span><span>유형</span><span>변경</span><span className="text-right">조치</span>
              </div>
              {activeNotices.slice(0, VISIBLE_NOTICE_LIMIT).map((notice) => {
                const status = noticeStatus(notice.id);
                const meta = caseMeta[notice.id];
                const changed = notice.current_version > 1;
                return (
                  <div key={notice.id} className="grid grid-cols-1 items-center gap-3 border-t border-[var(--product-line-2)] px-5 py-4 transition-colors hover:bg-[var(--product-tint)] lg:grid-cols-[132px_minmax(0,1fr)_180px_96px_112px_128px]">
                    <div>{metaLoading && !meta
                      ? <span className="inline-block rounded-full border border-[var(--product-line)] bg-[var(--product-tint)] px-3 py-1 text-[12px] font-semibold text-[var(--product-muted)]">판정 확인 중</span>
                      : <span className={`inline-block rounded-full border px-3 py-1 text-[12px] font-semibold ${STATUS_COPY[status].className}`}>{STATUS_COPY[status].label}</span>}</div>
                    <div className="min-w-0">
                      <strong className="block truncate text-[15px] font-bold text-[var(--product-ink)]">{notice.title}</strong>
                      <span className="mt-1 block text-[12px] text-[var(--product-muted)]">{notice.bid_notice_no}{meta?.judgment ? ` · 판정 ${meta.judgment.judgment_count}건 · 확인 필요 ${meta.judgment.unknown_count}건 · 미달 ${meta.judgment.unsatisfied_count}건` : ''}</span>
                    </div>
                    <span className="truncate text-[13px] text-[var(--product-muted)]">{notice.announcing_institution_name ?? '공고기관 미상'}</span>
                    <span className="text-[13px] text-[var(--product-muted)]">{labelOf(BUSINESS_TYPE_LABEL, notice.business_type)}</span>
                    {/*
                      차수가 1보다 크면 변경공고가 있었다는 뜻이다. 횟수는 백필 이력에 따라 달라질 수 있어 단정하지 않는다.
                      반대로 차수가 1이라고 원공고라고 말할 수는 없다 — 이력 백필(#129) 전에 수집된 공고는
                      변경이 있었어도 차수가 1로 남아 있다. 확인된 것만 쓴다.
                    */}
                    <span className={`text-[13px] ${changed ? 'font-semibold text-amber-700' : 'text-[var(--product-faint)]'}`}>{changed ? `변경 있음 · v${notice.current_version}` : '변경 여부 확인 전'}</span>
                    <div className="lg:text-right"><Button size="sm" onClick={() => void startReview(notice)} disabled={creatingNoticeId !== null} className="rounded-full px-4">{creatingNoticeId === notice.id ? <LoaderCircle className="animate-spin" /> : existingCaseByNotice.has(notice.id) ? '검토 보기' : '검토 시작'}<ArrowRight /></Button></div>
                  </div>
                );
              })}
            </div>
          ) : <div className="mt-7 rounded-[20px] border border-dashed border-[var(--product-line)] bg-[var(--product-tint)] px-6 py-16 text-center"><Search className="mx-auto size-8 text-[var(--product-faint)]" /><p className="mt-3 font-semibold">조회된 공고가 없습니다.</p><p className="mt-1 text-sm text-[var(--product-muted)]">검색어나 판정 상태 필터를 바꿔보세요.</p></div>}
        </section>

        <section className="mt-12 overflow-hidden rounded-[22px] border border-[var(--product-line)] bg-[var(--product-tint)]">
          <button type="button" onClick={() => setShowRejected((value) => !value)} className="flex w-full items-center gap-4 px-6 py-5 text-left"><ChevronDown className={`size-5 transition-transform ${showRejected ? 'rotate-180' : ''}`} /><div className="flex-1"><h3 className="text-[18px] font-bold text-[var(--product-ink)]">자격 미달로 접어둔 공고{metaLoading ? '' : ` ${rejectedNotices.length}건`}</h3><p className="mt-1 text-[13px] text-[var(--product-muted)]">숨기지 않습니다. 조건이나 회사 정보가 바뀌면 다시 검토할 수 있습니다.</p></div><span className="text-[13px] font-medium">{showRejected ? '접기' : '펼치기'}</span></button>
          {showRejected && <div className="border-t border-[var(--product-line)] bg-white px-6">{rejectedNotices.length ? rejectedNotices.map((notice) => {
            const meta = caseMeta[notice.id];
            return <div key={notice.id} className="flex flex-col gap-3 border-b border-[var(--product-line-2)] py-5 last:border-b-0 md:flex-row md:items-center"><span className={`w-fit rounded-full border px-3 py-1 text-[12px] font-semibold ${STATUS_COPY.ineligible.className}`}>자격 미달</span><div className="min-w-0 flex-1"><strong className="block truncate text-[15px]">{notice.title}</strong><span className="mt-1 block text-[12px] text-[var(--product-muted)]">{meta?.judgment ? `미달 ${meta.judgment.unsatisfied_count}건 · 확인 필요 ${meta.judgment.unknown_count}건` : notice.bid_notice_no}</span></div><button type="button" onClick={() => void startReview(notice)} className="text-left text-[13px] font-semibold text-[var(--product-accent-deep)]">근거 확인 →</button></div>;
          }) : <p className="py-8 text-center text-sm text-[var(--product-muted)]">{metaLoading ? '판정 상태를 불러오는 중입니다.' : '현재 자격 미달로 판정된 공고가 없습니다.'}</p>}</div>}
        </section>

        <section className="mt-12 grid gap-5 lg:grid-cols-[minmax(0,1fr)_452px]">
          <div className="rounded-[22px] border border-[var(--product-line)] bg-white p-7"><div className="flex items-center gap-3"><h2 className="text-[27px] font-extrabold tracking-[-0.035em]">공지사항</h2><Sparkles className="size-5 text-[var(--product-accent)]" /></div><div className="mt-5 divide-y divide-[var(--product-line-2)]">{[['데이터 연결', '공고·회사·판정 데이터를 실제 나라장터 수집 기준으로 연결합니다.'], ['근거 원칙', '판정 결과는 공고 원문 근거와 연결되는 경우에만 화면에 보여줍니다.'], ['변경공고', '변경공고는 이전 차수를 덮어쓰지 않고 판정 영향과 함께 추적합니다.']].map(([title, text]) => <div key={title} className="grid gap-2 py-5 sm:grid-cols-[130px_minmax(0,1fr)]"><strong className="text-[13px] text-[var(--product-accent-deep)]">{title}</strong><span className="text-[14px]">{text}</span></div>)}</div></div>
          <aside className="rounded-[22px] bg-[var(--product-accent-deep)] p-7 text-white"><div className="flex items-start justify-between gap-3"><div><p className="text-[12px] font-semibold text-white/65">확인 필요</p><h2 className="mt-1 text-[26px] font-extrabold">확인이 필요한 항목</h2></div><strong className="text-[34px]">{metaLoading ? '—' : unknownTotal}</strong></div><p className="mt-3 text-[14px] leading-6 text-white/75">정보가 부족한 항목은 미달로 만들지 않고 확인 필요로 남깁니다.</p><div className="mt-6 space-y-3">{Object.entries(ASK_BACK_REASON_COPY).map(([key, reason]) => <div key={key} className="rounded-2xl bg-white/10 p-4"><span className="flex items-center gap-2 text-[14px] font-semibold">{reason.canAnswer ? <CircleHelp className="size-4" /> : <ShieldCheck className="size-4" />} {reason.label}</span><p className="mt-2 text-[12px] leading-5 text-white/65">{reason.description}</p></div>)}</div>{firstUnknownCase ? <Link href={`/ask-back?caseId=${firstUnknownCase.id}`} className="mt-6 inline-flex items-center gap-2 text-[13px] font-bold">확인 필요 항목 보기 <ArrowRight className="size-4" /></Link> : <p className="mt-6 text-[13px] text-white/65">{metaLoading ? '판정 상태를 불러오는 중입니다' : '지금 답할 항목이 없습니다'}</p>}</aside>        </section>

        <section className="mt-12 flex flex-col justify-between gap-5 rounded-[24px] border border-[#d9ddf8] bg-[#f2f4ff] px-8 py-7 md:flex-row md:items-center"><div><h2 className="text-[25px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">채우면 판정이 더 정확해집니다</h2><p className="mt-2 text-[14px] text-[var(--product-muted)]">{missingProfile.length ? `${missingProfile.join(' · ')} 영역이 아직 비어 있습니다.` : '현재 기본 프로필 영역이 모두 연결되어 있습니다.'}</p></div><div className="flex items-center gap-4"><span className="text-[13px] font-semibold">{profile.total}개 영역 중 {profile.filled}개 연결</span><Link href="/company"><Button variant="outline" className="rounded-full border-[var(--product-accent)] bg-white text-[var(--product-accent-deep)]">프로필 보완</Button></Link></div></section>
      </div>
    </main>
  );
}
