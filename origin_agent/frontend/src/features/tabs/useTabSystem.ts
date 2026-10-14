import { useCallback, useEffect, useMemo, useState } from "react";
import { useSessionSite } from "../../hooks/useSessionSite";
import type { WebSocketState } from "../../hooks/useWebSocket";
import type { TabId } from "./registry";

/**
 * In-memory tab state machine. No persistence by design:
 * session switch and page reload both fall back to the chat tab.
 */
export function useTabSystem(ws: WebSocketState) {
  const [activeTabState, setActiveTabState] = useState<{ sessionId: string; tab: TabId }>({
    sessionId: ws.sessionId,
    tab: "chat",
  });
  // Reset the exposed tab synchronously before session-change effects run.
  const activeTab = activeTabState.sessionId === ws.sessionId ? activeTabState.tab : "chat";

  // Single site probe source for the whole tab system (survives tab switches).
  const siteStatus = useSessionSite(ws.sessionId);

  const enabledTabs = useMemo<Record<TabId, boolean>>(
    () => ({
      chat: true,
      resources: true,
      media: Boolean(ws.sessionId),
      variables: Boolean(ws.sessionId),
      subagents: Object.keys(ws.subagentSessions).length > 0,
      characters: true,
      site: siteStatus.status === "ready",
      llm: true,
      sandbox: true,
    }),
    [ws.sessionId, ws.subagentSessions, siteStatus.status],
  );

  // Session switch always returns to the chat tab.
  useEffect(() => {
    setActiveTabState({ sessionId: ws.sessionId, tab: "chat" });
  }, [ws.sessionId]);

  // Active tab became disabled -> fall back to chat.
  useEffect(() => {
    if (!enabledTabs[activeTab]) {
      setActiveTabState({ sessionId: ws.sessionId, tab: "chat" });
    }
  }, [activeTab, enabledTabs, ws.sessionId]);

  const switchTab = useCallback(
    (id: TabId) => {
      if (!enabledTabs[id]) return;
      setActiveTabState({ sessionId: ws.sessionId, tab: id });
    },
    [enabledTabs, ws.sessionId],
  );

  return { activeTab, enabledTabs, switchTab, siteStatus };
}
