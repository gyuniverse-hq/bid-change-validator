'use client';

import Link from 'next/link';
import { Bell, Menu } from 'lucide-react';

import { PageContainer } from '@/components/product/page-container';

const PRIMARY_NAV = [
  { label: '공고 찾기', href: '/notices', disabled: false },
  { label: '내 입찰 건', href: '/qualification', disabled: false },
  { label: '회사 프로필', href: '/company', disabled: false },
  { label: '서류함', href: '/documents', disabled: true },
  { label: '이용안내', href: '/guide', disabled: true },
] as const;

function isActive(pathname: string, href: string) {
  if (href === '/notices') return pathname === '/' || pathname.startsWith('/notices');
  if (href === '/qualification') {
    return (
      pathname.startsWith('/cases') ||
      ['/qualification', '/ask-back', '/evidence', '/evaluation', '/changes'].some((route) =>
        pathname.startsWith(route),
      )
    );
  }
  if (href === '/company') return pathname.startsWith('/company') || pathname.startsWith('/company-profile');
  return pathname.startsWith(href);
}

export function AppHeader({ pathname }: { pathname: string }) {
  return (
    <header className="app-header">
      <div className="app-utility-bar">
        <PageContainer className="flex h-full items-center justify-between text-[12.5px] leading-[19px]">
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
          <Link href="/notices" className="app-brand" aria-label="비드체크 공고 찾기">
            <span className="app-brand-mark" aria-hidden="true">B</span>
            <span className="app-brand-copy">
              <strong className="app-brand-name">비드체크</strong>
              <span className="app-brand-subtitle">입찰 참가자격 확인</span>
            </span>
          </Link>

          <nav className="app-primary-nav" aria-label="주요 메뉴">
            {PRIMARY_NAV.map((item) => {
              if (item.disabled) {
                return (
                  <span key={item.href} className="app-nav-link app-nav-link-disabled" aria-disabled="true">
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

          <div className="app-header-actions">
            <button type="button" className="app-header-action">
              <Bell className="size-[15px]" strokeWidth={1.7} />
              <span>알림</span>
            </button>
            <button type="button" className="app-header-action">
              <Menu className="size-[15px]" strokeWidth={1.7} />
              <span>전체메뉴</span>
            </button>
          </div>
        </PageContainer>
      </div>
    </header>
  );
}
