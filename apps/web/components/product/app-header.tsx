'use client';

import Link from 'next/link';
import { Bell, LogOut, Menu } from 'lucide-react';

import { PageContainer } from '@/components/product/page-container';
import type { AuthUser } from '@/lib/auth';

const PRIMARY_NAV = [
  { label: '공고 찾기', href: '/notices', disabled: false },
  { label: '내 입찰 건', href: '/qualification', disabled: false },
  { label: '회사 프로필', href: '/company', disabled: false },
  { label: '서류함', href: '/documents', disabled: true },
  { label: '이용안내', href: '/guide', disabled: true },
] as const;

function isActive(pathname: string, href: string) {
  if (href === '/notices') return pathname.startsWith('/notices');
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

export function AppHeader({
  pathname,
  user,
  onLogout,
}: {
  pathname: string;
  user: AuthUser;
  onLogout: () => void;
}) {
  return (
    <header className="app-header">
      <div className="app-utility-bar">
        <PageContainer className="flex h-full items-center justify-between text-[12.5px] leading-[19px]">
          {/* 우리가 쓰는 공고 데이터의 출처. 링크처럼 보이므로 실제 출처로 연결한다. */}
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <a href="https://www.g2b.go.kr" target="_blank" rel="noreferrer noopener" className="app-utility-action" aria-label="나라장터 (새 창으로 열림)">나라장터</a>
            <a href="https://www.pps.go.kr" target="_blank" rel="noreferrer noopener" className="app-utility-action" aria-label="조달청 (새 창으로 열림)">조달청</a>
          </div>
          <div className="flex items-center gap-4 text-[var(--product-muted)]">
            <span>{user.company_name ?? user.username}</span>
            <button type="button" className="app-utility-action" onClick={onLogout}>로그아웃</button>
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
                  <span
                    key={item.href}
                    className="app-nav-link app-nav-link-disabled"
                    aria-disabled="true"
                    title="준비 중입니다"
                  >
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

          {/*
            알림·전체메뉴는 아직 동작이 없다. 눌러도 아무 일이 없으면 고장난 것으로 읽히므로
            준비 중임을 상태로 드러낸다. 기능이 붙으면 disabled와 title을 함께 걷어낸다.
          */}
          <div className="app-header-actions">
            <button type="button" className="app-header-action" disabled title="준비 중입니다">
              <Bell className="size-[15px]" strokeWidth={1.7} />
              <span>알림</span>
            </button>
            <button type="button" className="app-header-action" disabled title="준비 중입니다">
              <Menu className="size-[15px]" strokeWidth={1.7} />
              <span>전체메뉴</span>
            </button>
            <button type="button" className="app-header-action" onClick={onLogout} aria-label="로그아웃">
              <LogOut className="size-[15px]" strokeWidth={1.7} />
              <span>로그아웃</span>
            </button>
          </div>
        </PageContainer>
      </div>
    </header>
  );
}
