'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Bot, MessageCircle, Send, X } from 'lucide-react';
import { ActionCard } from './action-card';
import { useActions } from './provider';
import { isLocked } from '@/lib/copilot-actions';
import { useCopilot } from './provider';
import { getSourceLocationLabel } from '@/lib/copilot-view-model';
import type { CopilotChatResponse, CopilotIntent } from '@/lib/copilot-api';
import './panel.css';

const pages = { '/qualification': 'QUALIFICATION', '/ask-back': 'ASK_BACK', '/evidence': 'EVIDENCE', '/changes': 'CHANGES' } as const;
const suggestions: [string, CopilotIntent][] = [
  ['참여 가능해?', 'QUALIFICATION_SUMMARY'], ['무엇을 확인해야 해?', 'REQUIRED_CHECKS'],
  ['판정 당시 회사정보', 'PROFILE_SNAPSHOT'], ['변경된 요건 보여줘', 'CHANGED_NOTICE'],
];
export function CopilotPanel() {
  const pathname = usePathname();
  const caseId = useSearchParams().get('caseId') ?? '';
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const page = pages[pathname as keyof typeof pages];
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const media = window.matchMedia('(min-width: 1024px)');
    const display = () => {
      element.close();
      if (open && page) { if (media.matches) element.show(); else element.showModal(); }
    };
    display(); media.addEventListener('change', display);
    return () => { media.removeEventListener('change', display); element.close(); };
  }, [open, page]);
  if (!page) return null;
  return <>
    <button ref={toggle} className="copilot-launch" aria-expanded={open} aria-controls="copilot-panel" onClick={() => setOpen(v => !v)}>
      <MessageCircle size={18} /> 공고 도우미
    </button>
    <dialog ref={dialog} id="copilot-panel" className="copilot-panel" aria-labelledby="copilot-title"
      onCancel={() => { setOpen(false); toggle.current?.focus(); }}>
      <header><Bot size={20} aria-hidden /><h2 id="copilot-title">공고 도우미</h2>
        <button aria-label="도우미 닫기" onClick={() => { setOpen(false); toggle.current?.focus(); }}><X size={20} /></button></header>
      <PanelBody key={caseId} caseId={caseId} page={page} />
    </dialog>
  </>;
}
function PanelBody({ caseId, page }: { caseId: string; page: typeof pages[keyof typeof pages] }) {
  const { store, state } = useCopilot(caseId);
  const [question, setQuestion] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [state.turns, state.busy]);
  const ask = (text: string, intent?: CopilotIntent) => { if (caseId) void store.ask(caseId, text, intent, page); };
  return <>
    <div className="copilot-content">
      {!state.turns.length && <div className="copilot-empty"><Bot size={64} aria-hidden />
        <h3>{caseId ? '이 공고, 무엇이 궁금하세요?' : '검토할 공고를 먼저 선택해 주세요.'}</h3>
        <p>저장된 판정과 공고문 근거를 함께 확인할 수 있어요.</p></div>}
      {caseId && <div className="copilot-suggestions">{suggestions.map(([text, intent]) =>
        <button key={intent} disabled={state.busy} onClick={() => { store.focus(caseId, null); ask(text, intent); }}>{text}</button>)}</div>}
      {state.focus && <button className="copilot-focus" onClick={() => store.focus(caseId, null)}>선택 요건: {state.focus} · 전체 보기</button>}
      <div role="log" aria-label="공고 도우미 대화" aria-live="polite">
        {state.turns.map(turn => <div key={turn.id} className="copilot-turn">
          <p className="copilot-question">{turn.question}</p>
          {turn.response && <Answer response={turn.response} caseId={caseId} onSelect={key => {
            store.focus(caseId, key, turn.response?.reply_context); ask('그 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE');
          }} />}
        </div>)}
      </div>
      {state.busy && <output>현재 검토 결과를 확인하고 있어요…</output>}
      {state.error && <div role="alert" className="copilot-error">
        {['CURRENT_JUDGMENT_REQUIRED', 'QUALIFICATION_JUDGMENT_NOT_FOUND', 'JUDGMENT_NOT_FOUND'].includes(state.errorCode)
          ? '저장된 판정이 아직 없습니다. 참가자격 화면에서 검토 상태를 확인해 주세요.' : state.error}
        <button disabled={state.busy} onClick={() => ask('현재 판정 결과', 'QUALIFICATION_SUMMARY')}>현재 결과 다시 조회</button>
      </div>}
      <ActionCard caseId={caseId} />
      <div ref={end} />
    </div>
    <form className="copilot-input" onSubmit={e => { e.preventDefault(); if (!question.trim() || state.busy || !caseId) return; ask(question); setQuestion(''); }}>
      <label className="sr-only" htmlFor="copilot-question">공고 질문</label>
      <input id="copilot-question" maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} placeholder="예: 두 번째 항목의 근거는?" disabled={!caseId} />
      <button aria-label="질문 보내기" disabled={!caseId || state.busy || !question.trim()}><Send size={18} /></button>
    </form>
  </>;
}
function Answer({ response, caseId, onSelect }: { response: CopilotChatResponse; caseId: string; onSelect: (key: string) => void }) {
  const p = response.presentation;
  const { controller, action } = useActions(caseId);
  return <article className="copilot-answer">
    {p ? <>
      <p className="copilot-conclusion">{p.conclusion}</p>
      {p.reasons.map((reason, i) => <div key={i} className="copilot-reason">
        <p>{reason.text}</p>
        {reason.requirement_key && <button onClick={() => onSelect(reason.requirement_key!)}>이 요건 근거 보기</button>}
        <span>{reason.evidence_refs.map(ref => '[' + ref + ']').join(' ')}</span>
      </div>)}
      {p.limitations.map((text, i) => <p className="copilot-limitation" key={i}>{text}</p>)}
      {p.next_action && <p>{p.next_action.label}</p>}
    </> : <p>{response.answer}</p>}
    {response.sources.length > 0 && <details><summary>원문 근거 {response.sources.length}건</summary>
      {response.sources.map(source => <div className="copilot-source" key={source.ref}>
        <strong>[{source.ref}] {getSourceLocationLabel(source)}</strong>
        <p>{source.source_origin === 'PRODUCT_EVIDENCE' ? source.evidence.quote : source.quote}</p>
        {source.source_origin === 'PRODUCT_EVIDENCE' && <Link href={'/evidence?caseId=' + encodeURIComponent(caseId) + '&evidence=' + encodeURIComponent(source.evidence.evidence_key)}>원문 화면에서 보기</Link>}
      </div>)}
    </details>}
    {response.product_state && 'profile_snapshot' in response.product_state && <details><summary>판정 당시 회사정보</summary><pre>{JSON.stringify(response.product_state.profile_snapshot, null, 2)}</pre></details>}
    {response.product_state && 'questions' in response.product_state && response.product_state.questions.filter(q => q.askable).map(q =>
      <button key={q.requirement_key} disabled={isLocked(action)} onClick={() => void controller.beginAnswer(caseId, q.requirement_key,
        response.reply_context?.last_read_receipt?.kind === 'product' ? response.reply_context.last_read_receipt.provenance.judgment_run_id : undefined)}>{q.question} · 답변 입력</button>)}
    {response.actions.map((proposal, i) => <button key={i} disabled={isLocked(action)} onClick={() => controller.adopt(caseId, proposal)}>서버 제안 검토 · 아직 실행 안 함</button>)}
  </article>;
}
