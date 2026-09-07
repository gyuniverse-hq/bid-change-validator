'use client';

import Link from 'next/link';
import { Bell, Menu } from 'lucide-react';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

type PageInfo = {
  title: string;
  description: string;
  breadcrumb: string;
  showTitleBand?: boolean;
};

const PAGE_INFO: Record<string, PageInfo> = {
  '/': {
    title: '공고 찾기',
    description: '회사 프로필과 공고 원문 근거를 기준으로 검토할 공고를 찾습니다.',
    breadcrumb: '홈 › 공고 찾기',
    showTitleBand: false,
  },
  '/qualification': {
    title: '참가자격 검토',
    description: '판정한 모든 항목에 공고 원문 근거를 함께 표시합니다',
    breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토',
  },
  '/ask-back': {
    title: '확인 필요에 답하기',
    description: '판정에 필요한 값만 질문하고, 답한 항목만 다시 판정합니다.',
    breadcrumb: '홈 › 내 입찰 건 › 확인 필요',
  },
  '/evidence': {
    title: '근거 원문 대조',
    description: '판정에 사용한 공고 원문과 회사 값을 같은 화면에서 대조합니다.',
    breadcrumb: '홈 › 내 입찰 건 › 근거 원문',
  },
  '/evaluation': {
    title: '평가 대응',
    description: '공고의 배점표와 회사 프로필 값을 나란히 확인합니다.',
    breadcrumb: '홈 › 내 입찰 건 › 평가 대응',
  },
  '/changes': {
    title: '변경 이력',
    description: '공고 차수별 변경 내용과 판정 영향을 추적합니다.',
    breadcrumb: '홈 › 내 입찰 건 › 변경 이력',
  },
  '/company-profile': {
    title: '회사 프로필',
    description: '공고 판정에 사용하는 회사 값을 출처와 함께 관리합니다.',
    breadcrumb: '홈 › 회사 프로필',
  },
};

const PRIMARY_NAV = [
  { label: '공고 찾기', href: '/', enabled: true },
  { label: '내 입찰 건', href: '/qualification', enabled: true },
  { label: '회사 프로필', href: '/company-profile', enabled: false },
  { label: '서류함', href: '/documents', enabled: false },
  { label: '이용안내', href: '/guide', enabled: false },
] as const;

function pageInfoFor(pathname: string): PageInfo {
  return PAGE_INFO[pathname] ?? {
    title: '비드체크',
    description: '입찰 공고의 참가자격과 변경 영향을 근거와 함께 검토합니다.',
    breadcrumb: '홈 › 비드체크',
  };
}

export function AppHeader({ pathname }: { pathname: string }) {
  return (
    <header className="app-header">
      <div className="app-utility-bar">
        <div className="app-shell-container flex h-full items-center justify-between gap-4 text-[12px]">
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <span>나라장터</span>
            <span>조달청</span>
          </div>
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <span>(주)그로우랩</span>
            <span>황수빈</span>
            <button type="button" className="app-utility-action">로그아웃</button>
          </div>
        </div>
      </div>

      <div className="app-gnb">
        <div className="app-shell-container flex h-full items-center gap-5">
          <Link href="/" className="app-brand" aria-label="비드체크 홈">
            <span className="app-brand-mark">B</span>
            <span className="min-w-0">
              <strong className="block text-[22px] leading-6 tracking-[-0.03em]">비드체크</strong>
              <span className="mt-1 block text-[11px] leading-4 text-[var(--product-muted)]">입찰 참가자격 확인</span>
            </span>
          </Link>

          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-10 lg:flex" aria-label="주요 메뉴">
            {PRIMARY_NAV.map((item) => {
              const active = item.enabled && (item.href === '/' ? pathname === '/' : pathname.startsWith(item.href));
              if (!item.enabled) {
                return (
                  <span key={item.href} className="app-nav-link opacity-45" aria-disabled="true">
                    {item.label}
                  </span>
                );
              }
              return (
                <Link key={item.href} href={item.href} className="app-nav-link" aria-current={active ? 'page' : undefined}>
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-5 text-[12px] text-[var(--product-muted)]">
            <button type="button" className="inline-flex items-center gap-1.5 hover:text-[var(--product-text)]">
              <Bell className="size-4" />
              <span className="hidden sm:inline">알림 2</span>
            </button>
            <button type="button" className="inline-flex items-center gap-1.5 hover:text-[var(--product-text)]">
              <Menu className="size-4" />
              <span className="hidden sm:inline">전체메뉴</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

export function TitleBand({ title, description, breadcrumb }: Omit<PageInfo, 'showTitleBand'>) {
  return (
    <section className="app-title-band">
      <div className="app-shell-container relative flex h-full items-center">
        <div className="min-w-0 pb-1">
          <h1 className="text-[32px] font-semibold leading-[44px] tracking-[-0.035em] text-[var(--product-text)]">{title}</h1>
          <p className="mt-1 text-[14px] leading-[21px] text-[var(--product-muted)]">{description}</p>
        </div>
        <p className="absolute right-0 bottom-7 hidden text-[12px] text-[var(--product-muted)] md:block">{breadcrumb}</p>
      </div>
    </section>
  );
}

export function AppFooter() {
  return (
    <footer className="app-footer">
      <div className="app-shell-container py-8">
        <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-[var(--product-line)] pb-5 text-[13px] font-medium">
          <span>개인정보처리방침</span>
          <span>이용약관</span>
          <span>공개 API 이용안내</span>
          <span>고객지원</span>
        </div>
        <div className="flex flex-col gap-5 pt-5 md:flex-row md:items-start">
          <div className="flex shrink-0 items-center gap-2.5">
            <span className="grid size-6 place-items-center rounded-md bg-[var(--product-accent)] text-[11px] font-bold text-white">B</span>
            <strong className="text-[16px]">비드체크</strong>
          </div>
          <p className="max-w-5xl text-[12px] leading-6 text-[var(--product-muted)]">
            ○○○○ 서울특별시 ○○구 ○○로 00, 0층 · 대표전화 00-0000-0000<br />
            본 화면의 공고 데이터는 전부 가상값입니다. 실제 나라장터 공고가 아닙니다. © 2026 BIDCHECK. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const page = pageInfoFor(pathname);
  const routeClass = pathname === '/' ? 'app-shell-route-home' : pathname === '/qualification' ? 'app-shell-route-qualification' : '';

  return (
    <div className="app-shell min-h-screen bg-[var(--product-background)] text-[var(--product-text)]">
      <AppHeader pathname={pathname} />
      {page.showTitleBand !== false && <TitleBand title={page.title} description={page.description} breadcrumb={page.breadcrumb} />}
      <div className={`app-shell-content ${routeClass}`}>{children}</div>
      <AppFooter />
    </div>
  );
}
