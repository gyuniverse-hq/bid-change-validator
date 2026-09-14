'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle, RefreshCw } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { listCompanies } from '@/lib/qualification-api';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';
import { openReviewTarget } from '@/lib/notice-review-target';
import { analysisBadgeLabel, OVERALL_STATUS_BADGE } from '@/lib/status-copy';

/** 선택 회사가 있으면 부모의 회사를 사용한다. 미전달 시 기존 첫 회사 동작을 유지한다. */
export function CachedNoticeMatches({ companyId: selectedCompanyId, refreshKey = 0 }: { companyId?: string | null; refreshKey?: number }) {
  const router = useRouter();
  const [matches, setMatches] = useState<NoticeMatch[]>([]);
  const [loadedCompanyId, setLoadedCompanyId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const generation = useRef(0);
  const actionLock = useRef(false);
  // 회사 전환 첫 render부터 이전 회사 자료를 숨긴다. effect 정리만 기다리지 않는다.
  const activeCompanyId = selectedCompanyId === undefined ? loadedCompanyId : selectedCompanyId ?? '';
  const sameCompany = activeCompanyId === loadedCompanyId;

  useEffect(() => {
    const request = ++generation.current;
    let alive = true;
    async function load() {
      setLoading(true); setError(''); setMatches([]); setBusy(null);
      try {
        const id = selectedCompanyId === undefined ? (await listCompanies())[0]?.id ?? '' : selectedCompanyId ?? '';
        if (!alive || request !== generation.current) return;
        setLoadedCompanyId(id);
        if (!id) return;
        const result = await listNoticeMatches(id, 12);
        if (alive && request === generation.current) setMatches(result.items);
      } catch (cause) {
        if (alive && request === generation.current) setError(cause instanceof Error ? cause.message : '미리 비교한 결과를 불러오지 못했습니다.');
      } finally {
        if (alive && request === generation.current) setLoading(false);
      }
    }
    void load();
    return () => { alive = false; generation.current += 1; };
  }, [selectedCompanyId, refreshKey, reloadKey]);

  async function openReview(match: NoticeMatch) {
    if (!activeCompanyId || actionLock.current || !sameCompany) return;
    actionLock.current = true;
    const request = generation.current;
    setBusy(match.notice_id); setError('');
    try {
      const id = await openReviewTarget({ noticeId: match.notice_id, bidNoticeNo: match.bid_notice_no,
        versionNumber: match.version_number, companyId: activeCompanyId });
      if (request === generation.current) router.push(`/qualification?caseId=${encodeURIComponent(id)}`);
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : '검토 건을 열지 못했습니다.');
    } finally {
      actionLock.current = false;
      if (request === generation.current) setBusy(null);
    }
  }

  if (!activeCompanyId && selectedCompanyId !== undefined) return null;
  return <section className="app-shell-container pt-8 pb-10" aria-label="회사 기준 미리 비교">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h2 className="text-[24px] font-extrabold tracking-[-0.035em]">회사 기준 미리 비교</h2>
        <p className="mt-2 text-[13px] text-[var(--product-muted)]">저장된 공고 분석과 현재 회사 정보를 비교한 미저장 결과입니다. 아래의 저장된 검토 상태와는 별개입니다.</p></div>
      <Button variant="outline" size="sm" onClick={() => setReloadKey((value) => value + 1)} disabled={loading}><RefreshCw /> 다시 비교</Button>
    </div>
    {error && <p role="alert" className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
    {loading || !sameCompany ? <p role="status" className="mt-5 flex items-center gap-2 text-sm"><LoaderCircle className="size-4 animate-spin" />미리 비교한 결과를 확인하고 있습니다.</p>
      : !error && matches.length ? <><p className="mt-3 text-xs text-[var(--product-muted)]">이번 조회 {matches.length}건 · 표시 {Math.min(matches.length, 6)}건 · 전체 공고의 집계가 아닙니다.</p>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">{matches.slice(0, 6).map((item) => {
          const meta = OVERALL_STATUS_BADGE[item.overall_status];
          return <article key={item.notice_id} className="rounded-[20px] border border-[var(--product-line)] bg-white p-5">
            <div className="flex items-center justify-between gap-2"><span className={`rounded-full px-3 py-1 text-[13px] font-bold ${meta.className}`}>미리 비교: {meta.label}</span><span className="text-xs">{analysisBadgeLabel(item.analysis_status)}</span></div>
            <h3 className="mt-4 line-clamp-2 text-[15px] font-bold leading-6">{item.title}</h3>
            <p className="mt-2 text-xs text-[var(--product-muted)]">{item.institution_name ?? '기관 미상'} · {item.bid_notice_no} · v{item.version_number}</p>
            {item.requirement_count ? <p className="mt-4 text-sm">충족 {item.satisfied_count} · 확인 {item.unknown_count} · 미달 {item.unsatisfied_count}</p> : <p className="mt-4 text-sm">자격요건 미확보</p>}
            <Button size="sm" className="mt-5 rounded-full" onClick={() => void openReview(item)} disabled={busy !== null}>{busy === item.notice_id ? <LoaderCircle className="animate-spin" /> : null} 검토 열기 <ArrowRight /></Button>
          </article>;
        })}</div></> : !error && <p className="mt-5 rounded-xl border border-dashed p-6 text-sm text-[var(--product-muted)]">이 회사로 미리 비교할 수 있는 공고가 이번 조회에 없습니다.</p>}
  </section>;
}
