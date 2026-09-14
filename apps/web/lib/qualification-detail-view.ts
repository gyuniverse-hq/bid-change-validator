/** 렌더링용 문구는 조회/분석 완전성/저장 판정을 혼동하지 않게 만든다. */
import type { QualificationJudgment } from './qualification-api';
import type { QualificationDetail } from './qualification-detail';
import { presentQualificationState, historicalLabel } from './qualification-state';

export function qualificationDetailView(detail: QualificationDetail) {
  const view = presentQualificationState(detail.state);
  return {
    ...view,
    historical: historicalLabel(detail.state),
    counts: detail.judgment ? {
      satisfied: detail.judgment.judgments.filter(x => x.status === 'SATISFIED').length,
      unknown: detail.judgment.judgments.filter(x => x.status === 'UNKNOWN').length,
      unsatisfied: detail.judgment.judgments.filter(x => x.status === 'UNSATISFIED').length,
    } : null,
    coverage: ({ COMPLETE: '검토 후보 처리 기록 완료 · 원문 의미의 정확성 보증은 아님',
      UNVERIFIED: '전체 요건 분석 여부 미확인', INCOMPLETE: '누락·미해결 후보 확인 필요',
      INVALID: '처리 기록 불일치', EMPTY: '검토 후보 미확보' } as Record<string, string>)[detail.state.coverage_state] ?? '분석 범위 확인 필요',
    emptyScope: !detail.analysis ? '분석 결과를 아직 확보하지 못했습니다.'
      : detail.analysis.status === 'FAILED' ? '분석이 실패해 판정에서 빠진 조건을 확인하지 못했습니다.'
      : '이번 실행에 기록된 판정 밖 항목이 없습니다. 발견하지 못한 요건까지 없다는 뜻은 아닙니다.',
  };
}
const PROFILE_FIELDS: Record<string, string> = {
  code: '업종코드', name: '명칭', region: '지역', company_size: '기업규모',
  role_name: '인력 역할', headcount: '인원', total_count: '총인원', observed_amount: '대조 실적금액',
  observed_count: '대조 실적건수', certification_code: '인증코드',
};
/** 현재 회사 데이터를 과거 판정에 썼던 값처럼 그리지 않는다. 판정이 보존한 비교 근거만 사용한다. */
export function recordedComparison(judgment: QualificationJudgment | null): string {
  if (!judgment) return '현재 선택된 판정 없음';
  if (judgment.basis_type === 'USER_ANSWER') return '저장된 사용자 답변 기준 · 답변 최신성은 별도 확인';
  const raw = (judgment as QualificationJudgment & { profile_refs?: unknown }).profile_refs;
  if (Array.isArray(raw)) {
    const values = raw.filter((x): x is { field: string; value: string } => Boolean(x) && typeof x === 'object'
      && typeof x.field === 'string' && typeof x.value === 'string' && Boolean(PROFILE_FIELDS[x.field]));
    if (values.length) return values.map(x => `${PROFILE_FIELDS[x.field]}: ${x.value}`).join(' · ');
  }
  return judgment.basis_type === 'PROFILE' ? '저장된 회사 프로필로 판정 · 상세 비교값 미제공' : '판정에 필요한 근거 확인 필요';
}
