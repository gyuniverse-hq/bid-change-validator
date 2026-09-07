'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';

import { AppFooter } from '@/components/product/app-footer';
import { AppHeader } from '@/components/product/app-header';
import { TitleBand, type TitleBandProps } from '@/components/product/title-band';

type PageInfo = TitleBandProps & {
  showTitleBand?: boolean;
};

const PAGE_INFO: Array<{ match: (pathname: string) => boolean; page: PageInfo }> = [
  {
    match: (pathname) => pathname === '/' || pathname.startsWith('/notices'),
    page: {
      title: '공고 찾기',
      description: '회사 프로필과 공고 원문 근거를 기준으로 검토할 공고를 찾습니다.',
      breadcrumb: '홈 › 공고 찾기',
      showTitleBand: false,
    },
  },
  {
    match: (pathname) => pathname.startsWith('/cases/') && pathname.endsWith('/qualification') || pathname === '/qualification',
    page: {
      title: '참가자격 검토',
      description: '판정한 모든 항목에 공고 원문 근거를 함께 표시합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 참가자격 검토',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/cases/') && pathname.endsWith('/questions') || pathname === '/ask-back',
    page: {
      title: '확인 필요에 답하기',
      description: '판정에 필요한 값만 질문하고, 답한 항목만 다시 판정합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 확인 필요',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/cases/') && pathname.endsWith('/evidence') || pathname === '/evidence',
    page: {
      title: '근거 원문 대조',
      description: '판정에 사용한 공고 원문과 회사 값을 같은 화면에서 대조합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 근거 원문',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/cases/') && pathname.endsWith('/evaluation') || pathname === '/evaluation',
    page: {
      title: '평가 대응',
      description: '평가 관련 원문과 대응에 필요한 정보를 함께 확인합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 평가 대응',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/cases/') && pathname.endsWith('/changes') || pathname === '/changes',
    page: {
      title: '변경 이력',
      description: '공고 차수별 변경 내용과 판정 영향을 추적합니다.',
      breadcrumb: '홈 › 내 입찰 건 › 변경 이력',
    },
  },
  {
    match: (pathname) => pathname.startsWith('/company') || pathname.startsWith('/company-profile'),
    page: {
      title: '회사 프로필',
      description: '공고 판정에 사용하는 회사 값을 출처와 함께 관리합니다.',
      breadcrumb: '홈 › 회사 프로필',
    },
  },
];

function pageInfoFor(pathname: string): PageInfo {
  return PAGE_INFO.find(({ match }) => match(pathname))?.page ?? {
    title: '비드체크',
    description: '입찰 공고의 참가자격과 변경 영향을 근거와 함께 검토합니다.',
    breadcrumb: '홈 › 비드체크',
  };
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const page = pageInfoFor(pathname);
  const legacyRouteClass = pathname === '/' ? 'app-shell-route-home' : pathname === '/qualification' ? 'app-shell-route-qualification' : '';

  return (
    <div className="app-shell min-h-screen bg-[var(--product-tint)] text-[var(--product-body)]">
      <AppHeader pathname={pathname} />
      {page.showTitleBand !== false && (
        <TitleBand title={page.title} description={page.description} breadcrumb={page.breadcrumb} />
      )}
      <div className={`app-shell-content ${legacyRouteClass}`}>{children}</div>
      <AppFooter />
    </div>
  );
}
