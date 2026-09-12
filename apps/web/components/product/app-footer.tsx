import Link from 'next/link';

import { PageContainer } from '@/components/product/page-container';

export function AppFooter() {
  return (
    <footer className="app-footer">
      <PageContainer className="flex min-h-[204px] flex-col items-start gap-[22px] pt-8 pb-10">
        <div className="flex w-full flex-wrap items-start gap-x-4 gap-y-2 border-b border-[var(--product-line)] pb-[18px] text-[13.5px] leading-5 text-[var(--product-body)]">
          {/*
            아래 넷은 아직 연결할 화면이 없다. 링크처럼 보이면 눌러보고 아무 일이 없어
            고장난 것으로 읽히므로, 연결되기 전까지는 회색 안내 문구로만 둔다.
          */}
          <span className="text-[var(--product-faint)]">개인정보처리방침</span>
          <span className="text-[var(--product-faint)]">이용약관</span>
          <span className="text-[var(--product-faint)]">공개 API 이용안내</span>
          <span className="text-[var(--product-faint)]">고객지원</span>
          <span className="rounded-full bg-[var(--product-tint-2)] px-2.5 py-0.5 text-[11.5px] text-[var(--product-faint)]">준비 중</span>
          {/* 아래 워크벤치만 실제로 연결된 화면이다. 위 네 항목은 아직 대상 화면이 없다. */}
          <Link
            href="/workbench"
            className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-[var(--product-line)] bg-white px-4 py-1.5 text-[14px] font-bold text-[var(--product-accent-deep)] transition-colors hover:border-[var(--product-accent)] hover:bg-[var(--product-accent-soft)]"
          >
            검토 워크벤치
            <span aria-hidden="true">→</span>
          </Link>
        </div>
        <div className="flex w-full flex-col items-start gap-5 md:flex-row md:gap-[30px]">
          <div className="flex shrink-0 items-center gap-[9px]">
            <span className="size-6 rounded-lg bg-[#A7AEBA]" aria-hidden="true" />
            <strong className="text-[15.5px] font-bold leading-[23px] tracking-[-0.025em] text-[var(--product-muted)]">
              비드체크
            </strong>
          </div>
          <p className="max-w-[1228px] text-[12.5px] leading-[24px] text-[var(--product-muted)]">
            실제 나라장터 공고 원문과 회사 프로필을 기반으로 참가자격과 변경 영향을 검토합니다.<br />
            판정 결과는 근거 원문과 함께 확인하고 최종 제출 전 담당자가 다시 검토해야 합니다. © 2026 BIDCHECK. All rights reserved.
          </p>
        </div>
      </PageContainer>
    </footer>
  );
}
