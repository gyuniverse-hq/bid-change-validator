'use client';

import Link from 'next/link';
import { Bell, Menu } from 'lucide-react';

import { PageContainer } from '@/components/product/page-container';

const PRIMARY_NAV = [
  { label: '공고 찾기', href: '/' },
  { label: '내 입찰 건', href: '/qualification' },
  { label: '회사 프로필', href: '/company', disabled: true },
  { label: '서류함', href: '/documents', disabled: true },
  { label: '이용안내', href: '/guide', disabled: true },
] as const;

function isActive(pathname: string, href: string) {
  if (href === '/') return pathname === '/' || pathname.startsWith('/notices');
  if (href === '/qualification') {
    return pathname.startsWith('/cases') || ['/qualification', '/ask-back', '/evidence', '/evaluation', '/changes'].some((route) => pathname.startsWith(route));
  }
  if (href === '/company') return pathname.startsWith('/company') || pathname.startsWith('/company-profile');
  return pathname.startsWith(href);
}

export function AppHeader({ pathname }: { pathname: string }) {
  return (
    <header className="app-header">
      <div className="app-utility-bar">
        <PageContainer className="flex h-full items-center justify-between gap-4 text-[12px]">
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <span>나라장터</span>
            <span>조달청</span>
          </div>
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <span>그린브릿지 글로벌 주식회사</span>
            <button type="button" className="app-utility-action">로그아웃</button>
          </div>
        </PageContainer>
      </div>

      <div className="app-gnb">
        <PageContainer className="flex h-full items-center gap-5">
          <Link href="/" className="app-brand" aria-label="비드체크 공고 찾기">
            <span className="app-brand-mark" aria-hidden="true">B</span>
            <span className="min-w-0">
              <strong className="block text-[22px] leading-6 tracking-[-0.03em]">비드체크</strong>
              <span className="mt-1 block text-[11px] leading-4 text-[var(--product-muted)]">입찰 참가자격 확인</span>
            </span>
          </Link>

          <nav className="hidden min-w-0 flex-1 items-center justify-center gap-10 lg:flex" aria-label="주요 메뉴">
            {PRIMARY_NAV.map((item) => {
              if (item.disabled) {
                return (
                  <span key={item.href} className="app-nav-link opacity-45" aria-disabled="true">
                    {item.label}
                  </span>
                );
              }

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="app-nav-link"
                  aria-current={isActive(pathname, item.href) ? 'page' : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-5 text-[12px] text-[var(--product-muted)]">
            <button type="button" className="inline-flex items-center gap-1.5 transition-colors hover:text-[var(--product-ink)]">
              <Bell className="size-4" />
              <span className="hidden sm:inline">알림</span>
            </button>
            <button type="button" className="inline-flex items-center gap-1.5 transition-colors hover:text-[var(--product-ink)]">
              <Menu className="size-4" />
              <span className="hidden sm:inline">전체메뉴</span>
            </button>
          </div>
        </PageContainer>
      </div>
    </header>
  );
}
