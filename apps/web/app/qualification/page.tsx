'use client';

import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { QualificationReviewWorkspace } from '@/components/product/qualification-review-workspace';

export default function QualificationPage() {
  const caseId = useSearchParams().get('caseId');
  // Case 변경 시 이전 비동기 요청과 근거 선택이 새 화면에 남지 않게 분리한다.
  return <>
    {caseId && <div className="app-shell-container pt-4 text-sm"><Link className="underline" href={`/qualification-graph?caseId=${encodeURIComponent(caseId)}`}>조건 그래프 분석·변경 비교 (별도 실험 경로)</Link></div>}
    <QualificationReviewWorkspace key={caseId ?? 'new'} caseId={caseId} />
  </>;
}
