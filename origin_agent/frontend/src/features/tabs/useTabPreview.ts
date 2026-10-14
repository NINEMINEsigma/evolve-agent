/**
 * Read-only data assembly for the tab preview. Projects already-loaded
 * snapshots from the shared TabDataProvider, the chat runtime store and the
 * WebSocket state into a pure TabPreviewInput, then runs the tab's selector.
 * No fetch, refresh, CRUD or loadResources call is made here; the only timer is
 * a local 1s tick while the resources preview is open with a next event.
 */
import { useEffect, useState } from "react";
import { useChatRuntimeStore } from "../chat/chatRuntimeStore";
import { TIMING } from "../../constants/timing";
import { useTabData } from "./TabDataContext";
import type { TabDefinition, TabRenderContext } from "./registry";
import type { TabPreviewInput, TabPreviewLlmInput, TabPreviewModel } from "./tabPreviewTypes";

function llmInput(ctx: TabRenderContext): TabPreviewLlmInput {
  const manager = ctx.ws.llmProfiles;
  if (manager == null) {
    return {
      profilesCount: null, profilesStatus: "loading", profilesError: null, profilesWarning: null,
      selectionStatus: "idle", selectionError: null, pendingProfileName: "",
      approvalStatus: "loading", metadataStatus: "loading", approvalError: null, metadataError: null,
      approvalProfileName: null, metadataProfileName: null, approvalAvailable: false, metadataAvailable: false,
    };
  }
  return {
    profilesCount: manager.profilesStatus === "ready" ? manager.profiles.length : null,
    profilesStatus: manager.profilesStatus,
    profilesError: manager.profilesError,
    profilesWarning: manager.profilesWarning,
    selectionStatus: manager.selectionStatus,
    selectionError: manager.selectionError,
    pendingProfileName: manager.activeProfileName,
    approvalStatus: manager.approvalStatus,
    metadataStatus: manager.metadataStatus,
    approvalError: manager.approvalError,
    metadataError: manager.metadataError,
    approvalProfileName: manager.approvalProfileName,
    metadataProfileName: manager.metadataProfileName,
    approvalAvailable: manager.approvalProfileState.available,
    metadataAvailable: manager.metadataProfileState.available,
  };
}

export function useTabPreview(tab: TabDefinition | null, ctx: TabRenderContext): TabPreviewModel | null {
  const tabData = useTabData();
  const [now, setNow] = useState(() => Date.now());
  const resources = useChatRuntimeStore((state) => state.resources);
  const resourcesLoading = useChatRuntimeStore((state) => state.resourcesLoading);
  const resourcesError = useChatRuntimeStore((state) => state.resourcesError);
  const runtimeSessionId = useChatRuntimeStore((state) => state.sessionId);
  const initialReady = useChatRuntimeStore((state) => state.initialReady);
  const processing = useChatRuntimeStore((state) => state.processing);
  const knownHistoryCount = useChatRuntimeStore((state) => state.knownHistoryCount);

  const cronData = ctx.ws.resourceSnapshots.cronTasks.data;
  const hasNextEvent = cronData !== null
    && cronData.some((task) => task.should_schedule && task.next_run !== null);

  // 仅资源预览打开且存在下一项时运行本地 1 秒 tick；关闭/换 Tab 立即清理。
  useEffect(() => {
    if (tab?.id !== "resources" || !hasNextEvent) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), TIMING.CRON_TICK);
    return () => window.clearInterval(timer);
  }, [tab?.id, hasNextEvent]);

  if (tab === null || tab.preview === undefined) return null;

  const sessionArchived = ctx.currentSessionArchived;
  const processingValid = runtimeSessionId === ctx.sessionId && initialReady;
  const input: TabPreviewInput = {
    sessionId: ctx.sessionId,
    sessionGeneration: ctx.ws.resourceScope.generation,
    sessionArchived,
    processing: sessionArchived ? false : processingValid ? processing : null,
    resources: resources === null || resources.session_id !== ctx.sessionId ? null : {
      sessionId: resources.session_id,
      images: resources.images.length,
      downloads: resources.downloads.length,
      loading: resourcesLoading,
      error: resourcesError,
    },
    knownHistoryCount,
    shells: ctx.ws.resourceSnapshots.shells,
    cronTasks: ctx.ws.resourceSnapshots.cronTasks,
    dynamicEndpoints: ctx.ws.resourceSnapshots.dynamicEndpoints,
    subagents: ctx.ws.subagentSessions,
    characters: {
      profiles: tabData.characters.profiles,
      loading: tabData.characters.loading,
      error: tabData.characters.error,
    },
    sandbox: {
      spaces: tabData.sandbox.spaces,
      loading: tabData.sandbox.loading,
      error: tabData.sandbox.error,
    },
    site: {
      status: ctx.siteStatus.status,
      indexUrl: ctx.siteStatus.urls?.indexUrl ?? "",
    },
    llm: llmInput(ctx),
    media: {
      aggregate: tabData.media.aggregate,
      loading: tabData.media.loading,
      error: tabData.media.error,
      stale: tabData.media.stale,
      archived: sessionArchived,
    },
    variables: {
      pool: tabData.variables.pool,
      loading: tabData.variables.loading,
      error: tabData.variables.error,
    },
    now,
  };

  return tab.preview(input);
}