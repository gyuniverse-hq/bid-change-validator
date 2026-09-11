'use client';

import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';

const Context = createContext<ConversationStore | null>(null);
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new ConversationStore());
  return <Context.Provider value={store}>{children}</Context.Provider>;
}
export function useCopilot(caseId: string) {
  const store = useContext(Context);
  if (!store) throw new Error('CopilotProvider required');
  const state = useSyncExternalStore(store.subscribe, () => store.get(caseId), () => store.get(caseId));
  return { store, state };
}
