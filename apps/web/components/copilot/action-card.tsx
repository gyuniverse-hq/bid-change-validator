'use client';
import { useActions } from './provider';
import { isLocked } from '@/lib/copilot-actions';

export function ActionCard({ caseId }: { caseId: string }) {
  const { controller, action } = useActions(caseId);
  if (action.stage === 'IDLE' && !action.busy && !action.message) return null;
  const locked = isLocked(action);
  const draft = action.draft;
  return <section className="rounded-2xl border border-violet-200 bg-white p-4 space-y-3 text-sm" aria-label="공통 작업 확인">
    <h3 className="font-bold">반영 내용 확인</h3>
    <p className="text-xs text-gray-600">이 검토 건에만 반영합니다. 회사 프로필은 변경하지 않습니다.</p>
    {draft && <>
      <p>{draft.label}</p>
      {(['satisfies_requirement', 'evidence_held'] as const).map(field => <label key={field} className="block">
        {field === 'satisfies_requirement' ? '이 요건을 충족하나요?' : '증빙을 보유하고 있나요?'}
        <select className="block w-full rounded border p-2 mt-1" disabled={locked} value={draft[field] === null ? '' : String(draft[field])}
          onChange={e => controller.edit(caseId, { [field]: e.target.value === '' ? null : e.target.value === 'true' })}>
          <option value="">선택해 주세요</option><option value="true">예</option><option value="false">아니요</option>
        </select>
      </label>)}
      <label className="block">답변 값 (필요한 경우)<input className="block w-full rounded border p-2 mt-1" maxLength={2000} value={draft.normalized_value} disabled={locked}
        onChange={e => controller.edit(caseId, { normalized_value: e.target.value })} /></label>
      <button className="rounded border px-3 py-2" disabled={locked || draft.satisfies_requirement === null || draft.evidence_held === null}
        onClick={() => void controller.propose(caseId)}>반영 제안 받기 · 아직 저장 안 함</button>
    </>}
    {action.proposal && <>
      <h4 className="font-semibold">{action.proposal.title}</h4><p>{action.proposal.consequences}</p>
      {action.proposal.action_type === 'REVALIDATE' ? <p>범위: 변경된 참가자격 요건 전체. 특정 요건만 선택하거나 제외할 수 없습니다.</p>
        : <p>대상: {action.proposal.requirement_key}<br />충족: {action.proposal.user_input.satisfies_requirement ? '예' : '아니요'} · 증빙: {action.proposal.user_input.evidence_held ? '예' : '아니요'}<br />값: {action.proposal.user_input.normalized_value || '미입력'}</p>}
      <button className="rounded bg-violet-700 px-3 py-2 text-white" disabled={locked || action.stage !== 'PROPOSAL_READY'}
        onClick={() => void controller.confirm(caseId, true)}>내용 확인 후 실행</button>
    </>}
    {action.busy && <output className="block">{action.stage === 'CONFIRMING' ? '반영 중입니다…' : action.stage === 'REFRESHING' ? '새 판정을 조회하고 있습니다…' : '확인하고 있습니다…'}</output>}
    {action.message && <p role={action.stage === 'COMPLETED' ? undefined : 'alert'}>{action.message}</p>}
    {action.response && <p className="font-semibold">{action.response.presentation?.conclusion ?? action.response.answer}</p>}
    {['DONE_REFRESH_FAILED', 'OUTCOME_UNKNOWN'].includes(action.stage) && <button className="rounded border px-3 py-2" disabled={action.busy}
      onClick={() => void controller.refresh(caseId)}>결과 조회만 다시 시도</button>}
    {!locked && <button className="ml-2 rounded border px-3 py-2" onClick={() => controller.cancel(caseId)}>작업 닫기</button>}
    <p className="text-xs text-gray-600">패널을 닫아도 진행 상태는 유지됩니다. 새로고침·탭 종료 후 실행 상태 복구는 지원하지 않습니다.</p>
  </section>;
}
