import { useCallback, useEffect, useMemo, useState } from "react";
import { useSessionSite } from "../../hooks/useSessionSite";
import type { WebSocketState } from "../../hooks/useWebSocket";
import type { TabId } from "./registry";

/**
 * In-memory tab state machine. No persistence by design:
 * session switch and page reload both fall back to the chat tab.
 */
export function useTabSystem(ws: WebSocketState) {
  const [activeTab, setActiveTab] = useState<TabId>("chat");

  // Single site probe source for the whole tab system (survives tab switches).
  const siteStatus = useSessionSite(ws.sessionId);

  const enabledTabs = useMemo<Record<TabId, boolean>>(
    () => ({
      chat: true,
      resources: true,
      subagents: Object.keys(ws.subagentSessions).length > 0,
      site: siteStatus.status === "ready",
      llm: true,
    }),
    [ws.subagentSessions, siteStatus.status],
  );

  // Session switch always returns to the chat tab.
  useEffect(() => {
    setActiveTab("chat");
  }, [ws.sessionId]);

  // Active tab became disabled -> fall back to chat.
  useEffect(() => {
    if (!enabledTabs[activeTab]) {
      setActiveTab("chat");
    }
  }, [activeTab, enabledTabs]);

  const switchTab = useCallback(
    (id: TabId) => {
      if (!enabledTabs[id]) return;
      setActiveTab(id);
    },
    [enabledTabs],
  );

  return { activeTab, enabledTabs, switchTab, siteStatus };
}
