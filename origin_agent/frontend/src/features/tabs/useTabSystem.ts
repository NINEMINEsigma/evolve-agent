import { useCallback, useEffect, useMemo, useState } from "react";
import { useSessionSite } from "../../hooks/useSessionSite";
import { useSessionFileChanges } from "../sessionFileChanges/useSessionFileChanges";
import { useSessionTabCapabilities } from "./useSessionTabCapabilities";
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
  // Single file changes source: the summary enables the tab and previews use the
  // same snapshot; no second hook instance is created by Layout, Tab or preview.
  const fileChangesRequestEnabled = ws.sessionId !== "" && ws.isReady && !ws.sessionLocked;
  const fileChanges = useSessionFileChanges(
    ws.sessionId, activeTab === "changes", fileChangesRequestEnabled,
  );
  const tabCapabilities = useSessionTabCapabilities(ws.sessionId);
  const capabilitySnapshot = tabCapabilities.capabilities;
  const capabilitySessionMatches = capabilitySnapshot?.session_id === ws.sessionId;
  const capabilityConfirmed = capabilitySessionMatches
    && (tabCapabilities.status === "ready" || tabCapabilities.status === "refreshing");
  const mediaCount = capabilitySessionMatches ? capabilitySnapshot?.media_count ?? 0 : 0;
  const variablesAvailable = capabilitySessionMatches && capabilitySnapshot?.variables_available === true;

  const enabledTabs = useMemo<Record<TabId, boolean>>(
    () => ({
      chat: true,
      activity: true,
      resources: true,
      changes: true,
      media: capabilityConfirmed && mediaCount > 0,
      variables: capabilityConfirmed && variablesAvailable,
      subagents: Object.keys(ws.subagentSessions).length > 0,
      characters: true,
      site: siteStatus.status === "ready",
      llm: true,
      sandbox: true,
    }),
    [ws.sessionId, ws.subagentSessions, siteStatus.status, tabCapabilities.status,
      capabilitySnapshot?.session_id, capabilitySnapshot?.media_count, capabilitySnapshot?.variables_available],
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

  return { activeTab, enabledTabs, switchTab, siteStatus, fileChanges };
}
