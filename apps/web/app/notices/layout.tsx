import type { ReactNode } from 'react';

import { CachedNoticeMatches } from '@/components/product/cached-notice-matches';

export default function NoticesLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <CachedNoticeMatches />
    </>
  );
}
