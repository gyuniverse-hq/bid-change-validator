import { Eye } from 'lucide-react';

import { Button } from '@/components/ui/button';

export type QualificationRowStatus = 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN' | 'UNJUDGED';

type QualificationRowProps = {
  status: QualificationRowStatus;
  condition: string;
  companyValue: string;
  evidenceLabel: string;
  actionLabel: string;
  onEvidence?: () => void;
  onAction?: () => void;
};

const STATUS_STYLE: Record<QualificationRowStatus, { label: string; className: string }> = {
  SATISFIED: { label: '충족', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  UNSATISFIED: { label: '미달', className: 'border-rose-200 bg-rose-50 text-rose-700' },
  UNKNOWN: { label: '확인 필요', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  UNJUDGED: { label: '미판정', className: 'border-slate-200 bg-slate-50 text-slate-600' },
};

export function QualificationRow({
  status,
  condition,
  companyValue,
  evidenceLabel,
  actionLabel,
  onEvidence,
  onAction,
}: QualificationRowProps) {
  const statusMeta = STATUS_STYLE[status];
  const userAnswerDerived = companyValue === '비어 있음' && (status === 'SATISFIED' || status === 'UNSATISFIED');

  return (
    <div className="grid min-h-[64px] grid-cols-1 border-t border-[var(--product-line-2)] lg:grid-cols-[122px_minmax(0,1.9fr)_minmax(190px,0.8fr)_170px_160px]">
      <div className="flex items-center px-3 py-3">
        <span className={`rounded-full border px-2.5 py-1 text-[12px] font-semibold ${statusMeta.className}`}>{statusMeta.label}</span>
      </div>
      <div className="flex items-center px-3 py-3 text-[14px] font-medium leading-6 text-[var(--product-body)]">{condition}</div>
      <div className="flex items-center px-3 py-3 text-[13px] leading-5 text-[var(--product-muted)]">
        {userAnswerDerived ? (
          <div>
            <span className="inline-flex rounded-full bg-[#eef1ff] px-2.5 py-1 text-[11px] font-bold text-[var(--product-accent-deep)]">USER_ANSWER</span>
            <p className="mt-1.5 font-medium text-[var(--product-body)]">사용자 답변으로 판정</p>
            <p className="text-[11.5px]">회사 프로필에는 값 없음</p>
          </div>
        ) : companyValue}
      </div>
      <div className="flex items-center px-3 py-3">
        <button
          type="button"
          onClick={onEvidence}
          disabled={!onEvidence}
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--product-accent-deep)] disabled:cursor-default disabled:text-[var(--product-faint)]"
        >
          <Eye className="size-4" /> {evidenceLabel}
        </button>
      </div>
      <div className="flex items-center px-3 py-3">
        {onAction ? (
          <Button size="sm" variant={status === 'UNKNOWN' ? 'default' : 'outline'} onClick={onAction} className="rounded-full">
            {actionLabel}
          </Button>
        ) : (
          <span className="text-[12px] text-[var(--product-faint)]">{actionLabel}</span>
        )}
      </div>
    </div>
  );
}
