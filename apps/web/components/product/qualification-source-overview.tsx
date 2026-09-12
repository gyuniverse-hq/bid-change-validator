import Link from 'next/link';

import { Button } from '@/components/ui/button';
import type { BidNoticeSummary, BidNoticeVersion, PreflightCase } from '@/lib/api';
import type { QualificationAnalysisRun } from '@/lib/qualification-api';
import { BUSINESS_TYPE_LABEL, EXTRACTION_STATUS_LABEL, VIEWER_TYPE_LABEL, labelOf } from '@/lib/status-copy';

function money(value: number | null | undefined) {
  return value == null ? '-' : `${value.toLocaleString()}원`;
}

function dateTime(value: string | null | undefined) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

type Props = {
  caseItem: PreflightCase;
  notice: BidNoticeSummary | null;
  version: BidNoticeVersion | null;
  analysis: QualificationAnalysisRun | null;
};

export function QualificationSourceOverview({ caseItem, notice, version, analysis }: Props) {
  // 아래 「판정에 들어가지 않은 조건」 섹션과 같은 기준으로 센다.
  // 여기만 code === 'UNMAPPED_REQUIREMENT'로 세면 UNKNOWN_LEGACY_TYPE이나 구조화에서 제외된 원문이
  // 있는 공고에서 이 배지와 아래 섹션의 건수가 어긋난다.
  const noticeFactCount = analysis?.diagnostics.filter((item) => item.kind === 'NOTICE_FACT').length ?? 0;
  const droppedCount = analysis?.dropped_requirements.length ?? 0;
  const unjudgedCount = noticeFactCount + droppedCount;
  /**
   * 분석 상태를 셋으로 나눈다.
   *  - NOT_RUN : 아직 검토를 실행하지 않았다. 세어본 적이 없으므로 0건이 아니다.
   *  - FAILED  : 실행했으나 첨부를 읽지 못했다. 확인하지 못한 것이지 없는 것이 아니다.
   *  - DONE    : SUCCEEDED · PARTIAL. 이때의 0건만 「확인했더니 없다」는 뜻이다.
   * 셋을 합치면 실행 전 화면이 「확인 후 0건」처럼 읽힌다.
   */
  const analysisState: 'NOT_RUN' | 'FAILED' | 'DONE' = !analysis
    ? 'NOT_RUN'
    : analysis.status === 'FAILED'
      ? 'FAILED'
      : 'DONE';
  // 강조는 「완료됐고 실제로 빠진 조건이 있을 때」만. 실행 전에 경고색이 켜지면 그것도 오해다.
  const highlight = analysisState === 'DONE' && unjudgedCount > 0;

  const summary = [
    ['입찰공고번호', caseItem.bid_notice_no],
    ['공고차수', `${caseItem.current_version_number}차`],
    ['공고기관', notice?.announcing_institution_name ?? '-'],
    ['사업유형', labelOf(BUSINESS_TYPE_LABEL, notice?.business_type)],
    ['계약방법', version?.contract_method ?? '-'],
    ['추정가격', money(version?.estimated_price)],
    ['배정예산', money(version?.allocated_budget)],
    ['입찰서 제출마감', dateTime(version?.bid_closed_at)],
    ['개찰일시', dateTime(version?.opened_at)],
  ];

  return (
    <>
      <section className="mt-7">
        <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">나라장터 공고 요약</h2><span className="text-[13.5px] text-[var(--product-muted)]">수집된 원본 필드만 표시합니다</span></div>
        <div className="mt-3 overflow-hidden rounded-[20px] border-t border-[var(--product-line)]">
          <div className="grid md:grid-cols-3">
            {summary.map(([label, value]) => <div key={label} className="grid min-h-[48px] grid-cols-[130px_minmax(0,1fr)] border-b border-[var(--product-line-2)] md:[&:not(:nth-child(3n))]:border-r"><span className="bg-[var(--product-tint)] px-4 py-3 text-[13px] text-[var(--product-muted)]">{label}</span><strong className="px-4 py-3 text-[13.5px] font-medium text-[var(--product-ink)]">{value}</strong></div>)}
          </div>
        </div>
      </section>

      <section className="mt-7 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.6fr)]">
        <div className="rounded-[20px] border border-[var(--product-line-2)] bg-white p-6">
          <div className="flex items-baseline justify-between gap-3"><div><h2 className="text-[20px] font-extrabold">제출·첨부 서류</h2><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">현재 차수에서 실제 수집된 문서입니다.</p></div><span className="text-[12px] text-[var(--product-muted)]">{version?.documents.length ?? 0}종</span></div>
          <div className="mt-4 divide-y divide-[var(--product-line-2)]">
            {version?.documents.length ? version.documents.map((document) => <div key={document.id} className="flex items-center gap-3 py-3"><div className="min-w-0 flex-1"><strong className="block truncate text-[13.5px]">{document.name}</strong><span className="mt-1 block text-[11.5px] text-[var(--product-muted)]">{labelOf(VIEWER_TYPE_LABEL, document.viewer_type)} · {labelOf(EXTRACTION_STATUS_LABEL, document.extraction_status)}{document.extracted_char_count != null ? ` · ${document.extracted_char_count.toLocaleString()}자` : ''}</span></div><Link href={`/evidence?caseId=${caseItem.id}`}><Button variant="outline" size="sm" className="rounded-full">원문 대조</Button></Link></div>) : <p className="py-6 text-center text-[13px] text-[var(--product-muted)]">현재 차수에 수집된 문서가 없습니다.</p>}
          </div>
        </div>

        <div className={`rounded-[20px] border p-6 ${highlight ? 'border-amber-200 bg-[#fffaf0]' : 'border-[var(--product-line-2)] bg-white'}`}>
          <div className="flex items-baseline justify-between gap-3"><div><h2 className="text-[20px] font-extrabold">판정에 들어가지 않은 조건</h2><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">억지 판정하지 않은 조건을 숨기지 않습니다.</p></div><span className={`text-[12px] font-bold ${highlight ? 'text-amber-800' : 'text-[var(--product-muted)]'}`}>{analysisState === 'NOT_RUN' ? '분석 전' : analysisState === 'FAILED' ? '확인 못 함' : `${unjudgedCount}건`}</span></div>
          {/* 여기서는 건수만 알린다. 같은 항목을 아래 「판정에 들어가지 않은 조건」 섹션이
              공고 원문 인용·근거 위치·원문 보기와 함께 이미 그린다. 진단 message는 code가 같으면
              문장이 전부 동일해서, 여기에 나열하면 똑같은 문장만 N줄 반복된다. */}
          {analysisState === 'NOT_RUN'
            ? <p className="mt-5 text-[13px] leading-6 text-[var(--product-muted)]">아직 자격검토를 실행하지 않았습니다. 검토를 실행하면 판정에서 빠진 조건을 여기에 함께 표시합니다.</p>
            : analysisState === 'FAILED'
              ? <p className="mt-5 text-[13px] leading-6 text-[var(--product-muted)]">분석이 완료되지 않아 판정에서 빠진 조건을 확인하지 못했습니다.</p>
              : unjudgedCount
                ? <p className="mt-5 text-[13px] leading-6 text-amber-900">공고에서 확인했지만 회사 프로필과 대조할 수 없어 판정하지 않은 조건이 {unjudgedCount}건 있습니다. 아래에서 공고 원문과 함께 확인해 주세요.</p>
                : <p className="mt-5 text-[13px] text-[var(--product-muted)]">이번 분석에서 판정 밖으로 빠진 조건이 없습니다.</p>}
        </div>
      </section>
    </>
  );
}
