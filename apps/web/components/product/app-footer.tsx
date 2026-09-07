import { PageContainer } from '@/components/product/page-container';

export function AppFooter() {
  return (
    <footer className="app-footer">
      <PageContainer className="py-8">
        <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-[var(--product-line)] pb-5 text-[13px] font-medium text-[var(--product-body)]">
          <span>개인정보처리방침</span>
          <span>이용약관</span>
          <span>공개 API 이용안내</span>
          <span>고객지원</span>
        </div>
        <div className="flex flex-col gap-5 pt-5 md:flex-row md:items-start">
          <div className="flex shrink-0 items-center gap-2.5">
            <span className="grid size-6 place-items-center rounded-md bg-[var(--product-accent)] text-[11px] font-bold text-white">B</span>
            <strong className="text-[16px] text-[var(--product-ink)]">비드체크</strong>
          </div>
          <p className="max-w-5xl text-[12px] leading-6 text-[var(--product-muted)]">
            실제 나라장터 공고 원문과 회사 프로필을 기반으로 참가자격과 변경 영향을 검토합니다.<br />
            판정 결과는 근거 원문과 함께 확인하고 최종 제출 전 담당자가 다시 검토해야 합니다. © 2026 BIDCHECK.
          </p>
        </div>
      </PageContainer>
    </footer>
  );
}
