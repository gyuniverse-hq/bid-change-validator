'use client';

import type { CopilotEnvelope } from '@/lib/copilot-v31';
import { CopilotNavigationLink } from './navigation-link';

const labels: Record<string, string> = { REQUIREMENT: '판정 요건', MANUAL: '직접 확인할 공고 항목', DOCUMENT: '공고문 근거', CHANGE: '변경 항목', ASSUMPTION: '검토용 가정' };

export function EnvelopeAnswer({ envelope, onTarget }: { envelope: CopilotEnvelope; onTarget: (id: string) => void }) {
  const sources = new Map(envelope.sources.map(source => [source.source_id, source]));
  return <section aria-label="근거 기반 검토 답변" data-copilot-version="3.1">
    {envelope.status_card && <output className="copilot-status-card">
      <strong>{envelope.status_card.text}</strong>
      <small>공고 v{envelope.status_card.provenance.version_number} · 저장된 판정 기준</small>
    </output>}
    {envelope.clarification && <p>{envelope.clarification}</p>}
    {envelope.claims.map(claim => <div className="copilot-claim" key={claim.claim_id}>
      <p style={{ whiteSpace: 'pre-wrap' }}>{claim.text}</p>
      <div className="copilot-evidence-chips">{claim.source_ids.map(id => {
        const source = sources.get(id);
        if (!source) return null;
        return <details key={id}><summary>{source.kind === 'DOCUMENT' ? '공고문 원문' : source.kind === 'TURN' ? '대화에서 제시한 가정' : '저장된 데이터'}</summary>
          <blockquote style={{ whiteSpace: 'pre-wrap' }}>{source.quote || '인용문을 표시하지 못했습니다.'}</blockquote>
          <small>버전 {source.scope.notice_version_id.slice(0, 8)} {typeof source.location.page === 'number' ? `· p.${source.location.page}` : ''}</small>
          {source.kind === 'DOCUMENT' && <CopilotNavigationLink caseId={source.scope.case_id} href={`/evidence?caseId=${encodeURIComponent(source.scope.case_id)}`}>원문 화면 열기</CopilotNavigationLink>}
        </details>;
      })}</div>
    </div>)}
    {envelope.follow_up_targets.length > 0 && <div aria-label="답변에서 확인한 항목">{envelope.follow_up_targets.map(target =>
      <button type="button" className="copilot-detail-link" key={target.target_id} onClick={() => onTarget(target.target_id)}>
        {labels[target.kind] ?? '확인 항목'} {target.ordinal} · 이 항목 근거 보기
      </button>)}</div>}
    {'answerable_count' in envelope.capabilities && <p>
      추가 답변 입력 가능 {envelope.capabilities.answerable_count}건 · 입력으로 해결할 수 없는 항목 {envelope.capabilities.unanswerable_count}건 · 직접 확인할 공고 항목 {envelope.capabilities.manual_review_count}건
    </p>}
    {envelope.limitations.map((text, index) => <p className="copilot-limitation" key={index}>{text}</p>)}
    {envelope.processing.task_status !== 'PASS' && <output>일부 요청은 추가 확인이 필요합니다.</output>}
  </section>;
}
