'use client';
import { createContext, useContext, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';
import { ActionController } from '@/lib/copilot-actions';

const Context = createContext<{ store: ConversationStore; controller: ActionController } | null>(null);
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [value] = useState(() => {
    const store = new ConversationStore();
    return { store, controller: new ActionController(undefined, undefined, (id, response) => store.publish(id, response)) };
  });
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
function useStores() {
  const stores = useContext(Context);
  if (!stores) throw new Error('CopilotProvider required');
  return stores;
}
export function useCopilot(caseId: string) {
  const { store } = useStores();
  const state = useSyncExternalStore(store.subscribe, () => store.get(caseId), () => store.get(caseId));
  return { store, state };
}
export function useActions(caseId: string) {
  const { controller } = useStores();
  const action = useSyncExternalStore(controller.subscribe, () => controller.get(caseId), () => controller.get(caseId));
  return { controller, action };
}
