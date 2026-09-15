'use client';

import Link from 'next/link';
import type { CopilotEnvelope } from '@/lib/copilot-v31';

const labels: Record<string, string> = { REQUIREMENT: '판정 요건', MANUAL: '직접 확인할 공고 항목', DOCUMENT: '공고문 근거', CHANGE: '변경 항목', ASSUMPTION: '검토용 가정' };
const progressLabels = { OPEN: '추가 검토 필요', ANSWERED: '설명 확인', AWAITING_CONFIRMATION: '실행 확인 대기', EXECUTED: '실행 결과 확인', UNAVAILABLE: '자료 확인 필요', STALE: '기준 변경 · 재확인 필요' };
const toolLabels: Record<string, string> = { READ_CHANGES: '변경 비교', READ_JUDGMENT: '저장 판정 조회', READ_PROFILE: '회사정보 조회', READ_CHECKS: '확인 항목 조회', READ_DOCUMENT: '공고문 조회', REVIEW_ASSUMPTION: '가정 검토', PROPOSE_ACTION: '변경 제안' };
const displayText = (text: string) => text.replace(/\b(?:READ_CHANGES|READ_JUDGMENT|READ_PROFILE|READ_CHECKS|READ_DOCUMENT|REVIEW_ASSUMPTION|PROPOSE_ACTION)\b/g, name => toolLabels[name]);

export function EnvelopeAnswer({ envelope, onTarget }: { envelope: CopilotEnvelope; onTarget: (id: string) => void }) {
  const sources = new Map(envelope.sources.map(source => [source.source_id, source]));
  return <section aria-label="근거 기반 검토 답변" data-copilot-version="3.1">
    {envelope.status_card && <output className="copilot-status-card">
      <strong>{envelope.status_card.text}</strong>
      <small>공고 v{envelope.status_card.provenance.version_number} · 저장된 판정 기준</small>
    </output>}
    {envelope.clarification && <p>{envelope.clarification}</p>}
    {envelope.job && <details className="copilot-job-progress">
      <summary>검토 목적과 남은 항목 · {envelope.job.status === 'COMPLETE' ? '요청 처리 완료' : '진행 중'}</summary>
      <p>{envelope.job.goal}</p>
      <ul>{envelope.job.requirements.map(item => <li key={item.requirement_id}>
        <strong>{progressLabels[item.status]}</strong> · {item.request}
        <small style={{ display: 'block' }}>{item.reason}</small>
      </li>)}</ul>
      <small>대화의 요청 처리 상태입니다. 참가자격 판정과는 별개이며 서버를 재시작하면 대화 기록이 초기화됩니다.</small>
    </details>}
    {envelope.claims.map(claim => <div className="copilot-claim" key={claim.claim_id}>
      <p style={{ whiteSpace: 'pre-wrap' }}>{displayText(claim.text)}</p>
      <div className="copilot-evidence-chips">{claim.source_ids.map(id => {
        const source = sources.get(id);
        if (!source) return null;
        return <details key={id}><summary>{source.kind === 'DOCUMENT' ? '공고문 원문' : source.kind === 'TURN' ? '대화에서 제시한 가정' : source.kind === 'PROCEDURE' ? '작업 안내' : '저장된 데이터'}</summary>
          <blockquote style={{ whiteSpace: 'pre-wrap' }}>{source.quote || '인용문을 표시하지 못했습니다.'}</blockquote>
          <small>버전 {source.scope.notice_version_id.slice(0, 8)} {typeof source.location.page === 'number' ? `· p.${source.location.page}` : ''}</small>
          {source.kind === 'DOCUMENT' && <Link href={`/evidence?caseId=${encodeURIComponent(source.scope.case_id)}`}>원문 화면 열기</Link>}
        </details>;
      })}</div>
    </div>)}
    {envelope.follow_up_targets.length > 0 && <div aria-label="답변에서 확인한 항목">{envelope.follow_up_targets.map(target =>
      <button type="button" className="copilot-detail-link" key={target.target_id} onClick={() => onTarget(target.target_id)}>
        {target.origin_tool === 'READ_PROFILE' ? '판정 당시 회사정보' : target.origin_tool === 'READ_CHECKS' && target.kind === 'REQUIREMENT' ? '추가 확인 질문' : labels[target.kind] ?? '확인 항목'} {target.ordinal} · 이 항목 근거 보기
      </button>)}</div>}
    {'answerable_count' in envelope.capabilities && <p>
      추가 답변 입력 가능 {envelope.capabilities.answerable_count}건 · 입력으로 해결할 수 없는 항목 {envelope.capabilities.unanswerable_count}건 · 직접 확인할 공고 항목 {envelope.capabilities.manual_review_count}건
    </p>}
    {envelope.limitations.map((text, index) => <p className="copilot-limitation" key={index}>{text}</p>)}
    {envelope.processing.task_status !== 'PASS' && <output>일부 요청은 추가 확인이 필요합니다.</output>}
  </section>;
}
