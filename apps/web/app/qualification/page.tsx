'use client';

import { useSearchParams } from 'next/navigation';
import { QualificationReviewWorkspace } from '@/components/product/qualification-review-workspace';

export default function QualificationPage() {
  const caseId = useSearchParams().get('caseId');
  // Case 변경 시 이전 비동기 요청과 근거 선택이 새 화면에 남지 않게 분리한다.
  return <QualificationReviewWorkspace key={caseId ?? 'new'} caseId={caseId} />;
}
