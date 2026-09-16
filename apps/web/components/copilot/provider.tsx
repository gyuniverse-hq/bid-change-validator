'use client';
import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';
import { ActionController } from '@/lib/copilot-actions';
import { saveCopilotNavigationHandoff, takeCopilotNavigationHandoff } from '@/lib/copilot-navigation-handoff';
import { navigateTo } from '@/lib/navigation';

type CopilotContextValue = {
  store: ConversationStore;
  controller: ActionController;
  reopenCaseId: string | null;
  consumeReopen: (caseId: string) => void;
};

const Context = createContext<CopilotContextValue | null>(null);
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [value] = useState(() => {
    const store = new ConversationStore();
    return { store, controller: new ActionController(undefined, undefined, (id, response) => store.publish(id, response)) };
  });
  const [reopenCaseId, setReopenCaseId] = useState<string | null>(null);
  const consumeReopen = useCallback((caseId: string) => {
    setReopenCaseId((current) => current === caseId ? null : current);
  }, []);

  useEffect(() => {
    const handoff = takeCopilotNavigationHandoff();
    if (!handoff) return;
    if (handoff.conversation) value.store.restore(handoff.caseId, handoff.conversation);
    if (handoff.action) value.controller.restore(handoff.caseId, handoff.action);
    if (handoff.reopenPanel) setReopenCaseId(handoff.caseId);
  }, [value]);
  return <Context.Provider value={{ ...value, reopenCaseId, consumeReopen }}>{children}</Context.Provider>;
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
export function useCopilotPanelRestore(caseId: string) {
  const { reopenCaseId, consumeReopen } = useStores();
  const consume = useCallback(() => consumeReopen(caseId), [caseId, consumeReopen]);
  return {
    shouldReopen: Boolean(caseId && reopenCaseId === caseId),
    consumeReopen: consume,
  };
}
export function useCopilotNavigation(caseId: string) {
  const { store, controller } = useStores();
  const stage = (destination: string, reopenPanel = false) => saveCopilotNavigationHandoff(
    destination,
    caseId,
    store.snapshot(caseId),
    controller.snapshot(caseId),
    reopenPanel,
  );
  return {
    stage,
    navigate: (destination: string, reopenPanel = true) => {
      stage(destination, reopenPanel);
      navigateTo(destination);
    },
  };
}
