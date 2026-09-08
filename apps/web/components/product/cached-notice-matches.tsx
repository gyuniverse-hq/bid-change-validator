'use client';

import { useEffect, useState } from 'react';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { getNoticeVersions, listPreflightCases } from '@/lib/api';
import { createPreflightCaseWithCompany, listCompanies } from '@/lib/qualification-api';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';

const STATUS = {
  eligible: { label: '응찰 가능', className: 'bg-emerald-50 text-emerald-700' },
  insufficient_data: { label: '확인 필요', className: 'bg-amber-50 text-amber-700' },
  ineligible: { label: '자격 미달', className: 'bg-rose-50 text-rose-700' },
} as const;

export function CachedNoticeMatches() {
  const router = useRouter();
  const [matches, setMatches] = useState<NoticeMatch[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const companies = await listCompanies();
        const company = companies[0];
        if (!company) return;
        setCompanyId(company.id);
        const result = await listNoticeMatches(company.id, 12);
        setMatches(result.items);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '회사 기준 매칭 결과를 불러오지 못했습니다.');
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  async function openReview(match: NoticeMatch) {
    if (!companyId) return;
    setBusy(match.notice_id);
    setError('');
    try {
      const cases = await listPreflightCases();
      const existing = cases.items.find((item) => item.notice_id === match.notice_id && item.company_id === companyId && item.current_version_number === match.version_number);
      if (existing) {
        router.push(`/qualification?caseId=${existing.id}`);
        return;
      }
      const versions = await getNoticeVersions(match.notice_id);
      const current = versions.find((item) => item.is_current) ?? versions[0];
      if (!current) throw new Error('현재 공고 버전을 찾지 못했습니다.');
      const baseline = versions.filter((item) => item.version_number < current.version_number).sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({
        notice_id: match.notice_id,
        company_id: companyId,
        baseline_version_number: baseline?.version_number,
        current_version_number: current.version_number,
        title: `${match.bid_notice_no} 참가자격 검토`,
      });
      router.push(`/qualification?caseId=${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건을 열지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <section className="app-shell-container py-8"><div className="grid min-h-28 place-items-center rounded-[22px] border border-[var(--product-line)]"><LoaderCircle className="size-6 animate-spin text-[var(--product-accent)]" /></div></section>;
  if (!companyId) return null;

  return (
    <section className="app-shell-container pb-14">
      <div className="border-t border-[var(--product-line)] pt-10">
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div><p className="text-[12px] font-bold text-[var(--product-accent-deep)]">PROFILE MATCH · ANALYZED ONLY</p><h2 className="mt-1 text-[27px] font-extrabold tracking-[-0.035em]">회사 기준으로 판정 가능한 공고</h2><p className="mt-2 text-[13px] text-[var(--product-muted)]">자격요건 분석이 이미 완료된 공고만 회사 프로필과 Rule로 비교했습니다. 미분석 공고는 이 결과에 포함하지 않습니다.</p></div><span className="text-[12px] text-[var(--product-muted)]">분석 완료 {matches.length}건</span>
        </div>
        {error && <p className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-[13px] text-rose-700">{error}</p>}
        {matches.length ? <div className="mt-5 grid gap-4 lg:grid-cols-3">{matches.slice(0, 6).map((item) => { const meta = STATUS[item.overall_status]; return <article key={item.notice_id} className="rounded-[20px] border border-[var(--product-line)] bg-white p-5"><div className="flex items-center justify-between"><span className={`rounded-full px-3 py-1 text-[12px] font-bold ${meta.className}`}>{meta.label}</span><span className="text-[11px] text-[var(--product-muted)]">분석 {item.analysis_status}</span></div><h3 className="mt-4 line-clamp-2 text-[16px] font-bold leading-6">{item.title}</h3><p className="mt-2 text-[12px] text-[var(--product-muted)]">{item.institution_name ?? '기관 미상'} · {item.bid_notice_no}</p><div className="mt-4 flex gap-3 text-[12px]"><span className="text-emerald-700">충족 {item.satisfied_count}</span><span className="text-amber-700">확인 {item.unknown_count}</span><span className="text-rose-700">미달 {item.unsatisfied_count}</span></div><Button size="sm" className="mt-5 rounded-full" onClick={() => void openReview(item)} disabled={busy !== null}>{busy === item.notice_id ? <LoaderCircle className="animate-spin" /> : null} 검토 열기 <ArrowRight /></Button></article>; })}</div> : <div className="mt-5 rounded-[20px] border border-dashed border-[var(--product-line)] px-6 py-10 text-center text-[13px] text-[var(--product-muted)]">아직 현재 공고 중 자격요건 분석이 완료된 후보가 없습니다. 공고 검토를 실행하면 캐시된 분석 결과가 이 영역에 누적됩니다.</div>}
      </div>
    </section>
  );
}
