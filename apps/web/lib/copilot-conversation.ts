import { sendCopilotMessage, type CopilotChatRequest, type CopilotChatResponse, type CopilotIntent, type ReplyContext } from './copilot-api';

export type Turn = { id: number; question: string; response?: CopilotChatResponse };
export type Conversation = { turns: Turn[]; busy: boolean; error: string; errorCode: string; focus: string | null; revision: number; reply?: ReplyContext };
const empty = (): Conversation => ({ turns: [], busy: false, error: '', errorCode: '', focus: null, revision: 0 });
export type Transport = (request: CopilotChatRequest) => Promise<CopilotChatResponse>;

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + canonical((value as Record<string, unknown>)[key])).join(',') + '}';
  return JSON.stringify(value);
}

export function validateSources(response: CopilotChatResponse) {
  const refs = response.sources.map(s => s.ref);
  const used = [...new Set([...response.answer.matchAll(/\[(S\d+)\]/g)].map(m => m[1]))];
  const required = response.presentation?.reasons.flatMap(r => r.evidence_refs) ?? [];
  if (refs.some((ref, i) => ref !== 'S' + (i + 1)) ||
      [...used, ...required].some(ref => !refs.includes(ref)) || required.some(ref => !used.includes(ref)) ||
      response.citations.length !== used.length || response.citations.some((source, i) =>
        source.ref !== used[i] || canonical(source) !== canonical(response.sources.find(s => s.ref === source.ref)))) {
    throw new Error('응답의 근거 연결을 확인하지 못했습니다. 다시 조회해 주세요.');
  }
}

// ponytail: layout-memory only; refresh discards conversation, never restores or retries writes.
export class ConversationStore {
  private states = new Map<string, Conversation>();
  private listeners = new Set<() => void>();
  constructor(private transport: Transport = sendCopilotMessage) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  get(caseId: string) {
    if (!this.states.has(caseId)) this.states.set(caseId, empty());
    return this.states.get(caseId)!;
  }
  private update(caseId: string, patch: Partial<Conversation>) {
    this.states.set(caseId, { ...this.get(caseId), ...patch });
    this.listeners.forEach(fn => fn());
  }
  focus(caseId: string, key: string | null, reply?: ReplyContext | null) {
    this.update(caseId, { focus: key, reply: reply ?? this.get(caseId).reply, revision: this.get(caseId).revision + 1, busy: false });
  }
  publish(caseId: string, response: CopilotChatResponse) {
    validateSources(response);
    const state = this.get(caseId), revision = state.revision + 1;
    this.update(caseId, { revision, busy: false, focus: null, reply: response.reply_context ?? undefined,
      error: '', errorCode: '', turns: [...state.turns, { id: revision, question: '반영 후 현재 결과', response }] });
  }
  async ask(caseId: string, question: string, intent?: CopilotIntent, page?: 'QUALIFICATION' | 'ASK_BACK' | 'EVIDENCE' | 'CHANGES') {
    const old = this.get(caseId);
    if (!caseId || old.busy || !question.trim()) return;
    const revision = old.revision + 1;
    this.update(caseId, { revision, busy: true, error: '', errorCode: '', turns: [...old.turns, { id: revision, question }] });
    try {
      const response = await this.transport({
        case_id: caseId, message: question, intent, requirement_key: old.focus,
        conversation_context: { request_id: crypto.randomUUID(), context_revision: revision, source_page: page,
          visible_requirement_keys: old.reply?.visible_requirement_keys ?? [], last_read_receipt: old.reply?.last_read_receipt,
          last_response_intent: old.turns.at(-1)?.response?.intent },
      });
      validateSources(response);
      if (this.get(caseId).revision !== revision) return;
      this.update(caseId, { busy: false, reply: response.reply_context ?? undefined,
        focus: response.reply_context?.requirement_key ?? null,
        turns: this.get(caseId).turns.map(t => t.id === revision ? { ...t, response } : t) });
    } catch (error) {
      if (this.get(caseId).revision !== revision) return;
      this.update(caseId, { busy: false, error: error instanceof Error ? error.message : '조회하지 못했습니다.',
        errorCode: error && typeof error === 'object' && 'code' in error ? String(error.code) : '' });
    }
  }
}
