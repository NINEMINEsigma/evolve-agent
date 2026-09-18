import { create } from "zustand";
import type { ChatMessage, MessageContent } from "../../types";
import type {
  ChatFollowMode,
  ChatHistoryPageError,
  ChatScrollMetrics,
  ChatVisibleRange,
  HistoryResourcesResponseDto,
  HistorySkeletonRowDto,
  LiveChatRow,
  PendingChatMessage,
  PendingStreamFinish,
  StreamBatch,
} from "./types";
import { generateUUID } from "../../utils";
import { MINIMAP_MEASUREMENT_EPSILON_PX } from "../../constants/history";
import { isLongChatMessage } from "./messageCollapse";

interface ChatRuntimeState {
  sessionId: string;
  generation: number;
  skeleton: HistorySkeletonRowDto[];
  knownHistoryCount: number;
  lastUserHistoryIndex: number;
  skeletonLoading: boolean;
  skeletonError: string | null;
  contentByRowId: Record<string, ChatMessage>;
  loadedHistoryIndices: Set<number>;
  pageErrors: Record<string, ChatHistoryPageError>;
  initialReady: boolean;
  liveRows: LiveChatRow[];
  pendingStreamFinishes: Record<string, PendingStreamFinish>;
  streamHistoryLinks: Record<string, string>;
  liveVersion: number;
  currentStreamId: string | null;
  processing: boolean;
  draftHtml: string;
  draftText: string;
  pendingMessages: Record<string, PendingChatMessage>;
  followMode: ChatFollowMode;
  visibleRange: ChatVisibleRange;
  scrollMetrics: ChatScrollMetrics;
  rowHeights: Record<string, number>;
  atBottom: boolean;
  userHeightMutation: boolean;
  resources: HistoryResourcesResponseDto | null;
  resourcesLoading: boolean;
  resourcesError: string | null;

  beginSession: (sessionId: string) => number;
  resetSession: () => void;
  setSkeletonLoading: (loading: boolean) => void;
  setSkeletonError: (error: string | null) => void;
  replaceSkeleton: (rows: HistorySkeletonRowDto[], historyCount: number) => void;
  appendSkeleton: (rows: HistorySkeletonRowDto[], historyCount: number) => void;
  mergeHistoryPage: (messages: ChatMessage[], startIndex: number, endIndex: number, canonicalCutoff?: number) => void;
  toggleMessageCollapse: (id: string, source: "history" | "live") => void;
  linkStreamHistory: (streamId: string, historyIndex: number) => void;
  setPageError: (error: ChatHistoryPageError | null) => void;
  clearCanonicalContent: () => void;
  setInitialReady: (ready: boolean) => void;
  appendLiveMessage: (message: ChatMessage, streaming?: boolean) => number;
  applyStreamBatch: (batch: StreamBatch) => void;
  queueStreamFinish: (streamId: string, content?: string, metrics?: import("../../types").MessageMetrics) => void;
  finishStream: (streamId: string, content?: string, metrics?: import("../../types").MessageMetrics, visibleAtFinish?: boolean) => void;
  reconcileCanonicalTail: (canonicalCutoff: number) => void;
  clearLive: () => void;
  setProcessing: (processing: boolean) => void;
  setDraft: (html: string, text: string) => void;
  addPendingMessage: (clientMessageId: string, content: MessageContent) => void;
  removePendingMessages: (ids: string[]) => void;
  clearPendingMessages: () => void;
  setFollowMode: (mode: ChatFollowMode) => void;
  setVisibleRange: (range: ChatVisibleRange) => void;
  setScrollMetrics: (metrics: ChatScrollMetrics) => void;
  mergeRowHeights: (entries: Array<{ id: string; height: number }>) => void;
  removeRowHeights: (ids: string[]) => void;
  setAtBottom: (atBottom: boolean) => void;
  beginUserHeightMutation: () => void;
  finishUserHeightMutation: (atBottom: boolean) => void;
  setResourcesLoading: (loading: boolean) => void;
  setResources: (resources: HistoryResourcesResponseDto | null) => void;
  setResourcesError: (error: string | null) => void;
}

const initialState = {
  sessionId: "",
  generation: 0,
  skeleton: [] as HistorySkeletonRowDto[],
  knownHistoryCount: 0,
  lastUserHistoryIndex: -1,
  skeletonLoading: false,
  skeletonError: null as string | null,
  contentByRowId: {} as Record<string, ChatMessage>,
  loadedHistoryIndices: new Set<number>(),
  pageErrors: {} as Record<string, ChatHistoryPageError>,
  initialReady: false,
  liveRows: [] as LiveChatRow[],
  pendingStreamFinishes: {} as Record<string, PendingStreamFinish>,
  streamHistoryLinks: {} as Record<string, string>,
  liveVersion: 0,
  currentStreamId: null as string | null,
  processing: false,
  draftHtml: "",
  draftText: "",
  pendingMessages: {} as Record<string, PendingChatMessage>,
  followMode: "initializing" as ChatFollowMode,
  visibleRange: { startIndex: 0, endIndex: 0 },
  scrollMetrics: { scrollTop: 0, scrollHeight: 0, viewportHeight: 0 },
  rowHeights: {} as Record<string, number>,
  atBottom: true,
  userHeightMutation: false,
  resources: null as HistoryResourcesResponseDto | null,
  resourcesLoading: false,
  resourcesError: null as string | null,
};

const lastUserIndex = (rows: HistorySkeletonRowDto[], fallback = -1): number => {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].row_kind === "message" && rows[index].role === "user") {
      return rows[index].history_index;
    }
  }
  return fallback;
};

const historyMatchesLive = (history: ChatMessage, live: LiveChatRow, historyId: string): boolean => (
  history.id === historyId
  && history.role === "assistant"
  && live.message.role === "assistant"
  && (history.characterName == null || live.message.characterName == null
    || history.characterName === live.message.characterName)
);

export const useChatRuntimeStore = create<ChatRuntimeState>((set, get) => ({
  ...initialState,

  beginSession: (sessionId) => {
    const nextGeneration = get().generation + 1;
    set({
      ...initialState,
      sessionId,
      generation: nextGeneration,
      loadedHistoryIndices: new Set<number>(),
    });
    return nextGeneration;
  },

  resetSession: () => {
    const nextGeneration = get().generation + 1;
    set({ ...initialState, generation: nextGeneration, loadedHistoryIndices: new Set<number>() });
  },

  setSkeletonLoading: (skeletonLoading) => set({ skeletonLoading }),
  setSkeletonError: (skeletonError) => set({ skeletonError }),

  replaceSkeleton: (skeleton, knownHistoryCount) => set({
    skeleton,
    knownHistoryCount,
    lastUserHistoryIndex: lastUserIndex(skeleton),
    contentByRowId: {},
    streamHistoryLinks: {},
    pendingStreamFinishes: {},
    loadedHistoryIndices: new Set<number>(),
    pageErrors: {},
  }),

  appendSkeleton: (rows, knownHistoryCount) => set((state) => ({
    skeleton: rows.length ? [...state.skeleton, ...rows] : state.skeleton,
    knownHistoryCount,
    lastUserHistoryIndex: lastUserIndex(rows, state.lastUserHistoryIndex),
  })),

  mergeHistoryPage: (messages, startIndex, endIndex, canonicalCutoff) => set((state) => {
    const contentByRowId = { ...state.contentByRowId };
    const transferred = new Set<string>();
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    for (const message of messages) {
      const previous = contentByRowId[message.id];
      const link = Object.entries(streamHistoryLinks).find(([, rowId]) => rowId === message.id);
      const live = link && state.liveRows.find((row) => row.id === link[0]);
      const matches = Boolean(live && !live.streaming && historyMatchesLive(message, live, message.id)
        && message.messageIndex === Number(message.id.split(":")[1]));
      const transferredCollapse = matches && live?.preserveExpanded ? live.message.collapsed : undefined;
      contentByRowId[message.id] = previous?.collapsed !== undefined
        ? { ...message, collapsed: previous.collapsed }
        : transferredCollapse === undefined ? message : { ...message, collapsed: transferredCollapse };
      if (link && !live?.streaming) {
        delete streamHistoryLinks[link[0]];
        if (matches) transferred.add(link[0]);
      }
    }
    const liveRows = state.liveRows.filter((row) => {
      if (transferred.has(row.id)) return false;
      if (canonicalCutoff === undefined || row.version > canonicalCutoff) return true;
      return Boolean(streamHistoryLinks[row.id]);
    });
    const remaining = new Set(liveRows.map((row) => row.id));
    const pendingStreamFinishes = Object.fromEntries(
      Object.entries(state.pendingStreamFinishes).filter(([id]) => remaining.has(id)),
    );
    const rowHeights = { ...state.rowHeights };
    for (const row of state.liveRows) if (!remaining.has(row.id)) delete rowHeights[row.id];
    const loadedHistoryIndices = new Set(state.loadedHistoryIndices);
    for (let index = startIndex; index < endIndex; index += 1) {
      loadedHistoryIndices.add(index);
    }
    const pageErrors = Object.fromEntries(
      Object.entries(state.pageErrors).filter(([, error]) =>
        error.endIndex <= startIndex || error.startIndex >= endIndex),
    );
    return { contentByRowId, loadedHistoryIndices, pageErrors, liveRows, streamHistoryLinks, pendingStreamFinishes, rowHeights };
  }),

  toggleMessageCollapse: (id, source) => set((state) => {
    if (source === "history") {
      const message = state.contentByRowId[id];
      if (!message) return state;
      return {
        contentByRowId: {
          ...state.contentByRowId,
          [id]: { ...message, collapsed: message.collapsed === false },
        },
      };
    }
    const index = state.liveRows.findIndex((row) => row.id === id);
    if (index < 0) return state;
    const liveRows = [...state.liveRows];
    const row = liveRows[index];
    liveRows[index] = {
      ...row,
      message: { ...row.message, collapsed: row.message.collapsed === false },
      collapseManuallyChanged: true,
    };
    return { liveRows };
  }),

  linkStreamHistory: (streamId, historyIndex) => set((state) => {
    if (!streamId || !Number.isSafeInteger(historyIndex) || historyIndex < 0) return state;
    const live = state.liveRows.find((row) => row.id === streamId && row.message.role === "assistant");
    if (!live) return state;
    const historyId = `history:${historyIndex}:message`;
    const existingLink = state.streamHistoryLinks[streamId];
    if (existingLink && existingLink !== historyId) return state;
    const skeleton = state.skeleton.find((row) => row.row_id === historyId);
    if (skeleton && (skeleton.row_kind !== "message" || skeleton.role !== "assistant"
      || (skeleton.character_name && live.message.characterName
        && skeleton.character_name !== live.message.characterName))) return state;
    const history = state.contentByRowId[historyId];
    if (!history || live.streaming) {
      return { streamHistoryLinks: { ...state.streamHistoryLinks, [streamId]: historyId } };
    }
    if (!historyMatchesLive(history, live, historyId) || history.messageIndex !== historyIndex) return state;
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    delete streamHistoryLinks[streamId];
    const rowHeights = { ...state.rowHeights };
    delete rowHeights[streamId];
    return {
      streamHistoryLinks,
      rowHeights,
      liveRows: state.liveRows.filter((row) => row.id !== streamId),
      contentByRowId: live.preserveExpanded && history.collapsed === undefined
        ? { ...state.contentByRowId, [historyId]: { ...history, collapsed: live.message.collapsed } }
        : state.contentByRowId,
    };
  }),

  setPageError: (error) => set((state) => {
    const pageErrors = { ...state.pageErrors };
    if (error) pageErrors[error.key] = error;
    else {
      for (const key of Object.keys(pageErrors)) delete pageErrors[key];
    }
    return { pageErrors };
  }),

  clearCanonicalContent: () => set({
    contentByRowId: {},
    streamHistoryLinks: {},
    pendingStreamFinishes: {},
    loadedHistoryIndices: new Set<number>(),
    pageErrors: {},
    initialReady: false,
  }),

  setInitialReady: (initialReady) => set({ initialReady }),

  appendLiveMessage: (message, streaming = false) => {
    const version = get().liveVersion + 1;
    set((state) => ({
      liveVersion: version,
      liveRows: [...state.liveRows, {
        id: message.id || generateUUID(),
        version,
        message,
        streaming,
        frozen: false,
      }],
      currentStreamId: streaming ? message.id : state.currentStreamId,
    }));
    return version;
  },

  applyStreamBatch: (batch) => set((state) => {
    const version = state.liveVersion + 1;
    const existing = state.liveRows.find((row) => row.id === batch.streamId);
    const base: ChatMessage = existing?.message ?? {
      role: "assistant",
      content: "",
      id: batch.streamId,
      characterName: batch.characterName,
    };
    const content = typeof base.content === "string" ? base.content : "";
    const mergedToolArgsRawMap = batch.toolArgsRawMap
      ? Object.entries(batch.toolArgsRawMap).reduce<Record<string, string>>((result, [key, value]) => {
          result[key] = (base.toolArgsRawMap?.[key] || "") + value;
          return result;
        }, { ...(base.toolArgsRawMap || {}) })
      : base.toolArgsRawMap;
    const nextMessage: ChatMessage = {
      ...base,
      content: content + batch.delta,
      reasoningContent: ((base.reasoningContent || "") + batch.reasoningDelta) || undefined,
      characterName: batch.characterName ?? base.characterName,
      toolName: batch.toolName ?? base.toolName,
      toolArgs: batch.toolArgs ?? base.toolArgs,
      toolArgsRawMap: batch.toolArgs ? undefined : mergedToolArgsRawMap,
      activeToolCallKey: batch.toolArgs ? undefined : (batch.activeToolCallKey ?? base.activeToolCallKey),
    };
    const liveRows = existing
      ? state.liveRows.map((row) => row.id === batch.streamId
          ? { ...row, version, message: nextMessage, streaming: true, frozen: false }
          : row)
      : [...state.liveRows, {
          id: batch.streamId,
          version,
          message: nextMessage,
          streaming: true,
          frozen: false,
        }];
    return {
      liveRows,
      liveVersion: version,
      currentStreamId: batch.streamId,
      processing: true,
    };
  }),

  queueStreamFinish: (streamId, content, metrics) => set((state) => {
    const live = state.liveRows.find((row) => row.id === streamId && row.streaming);
    if (!live || state.pendingStreamFinishes[streamId]) return state;
    return {
      pendingStreamFinishes: {
        ...state.pendingStreamFinishes,
        [streamId]: { streamId, content, metrics },
      },
      liveRows: state.liveRows.map((row) => row.id === streamId
        ? { ...row, message: { ...row.message, content: content || row.message.content } }
        : row),
    };
  }),

  finishStream: (streamId, content, metrics, visibleAtFinish = false) => {
    set((state) => {
      const pendingStreamFinishes = { ...state.pendingStreamFinishes };
      delete pendingStreamFinishes[streamId];
      const existing = state.liveRows.find((row) => row.id === streamId);
      if (!existing && !state.pendingStreamFinishes[streamId]) return state;
      const version = state.pendingStreamFinishes[streamId]
        ? (existing?.version ?? state.liveVersion) : state.liveVersion + 1;
      return {
        pendingStreamFinishes,
        liveVersion: state.pendingStreamFinishes[streamId] ? state.liveVersion : version,
        currentStreamId: state.currentStreamId === streamId ? null : state.currentStreamId,
        liveRows: state.liveRows.map((row) => {
          if (row.id !== streamId) return row;
          const message = {
            ...row.message,
            content: content || row.message.content,
            reasoningDuration: metrics?.reasoning_duration_ms ?? row.message.reasoningDuration,
            contentDuration: metrics?.content_duration_ms ?? row.message.contentDuration,
            completionTokens: metrics?.completion_tokens ?? row.message.completionTokens,
            tokensPerSecond: metrics?.tokens_per_second ?? row.message.tokensPerSecond,
          };
          const preserveExpanded = row.streaming && visibleAtFinish
            && message.role === "assistant" && !message.isSystemStatus
            && isLongChatMessage(message) && !row.collapseManuallyChanged;
          return {
            ...row, version, streaming: false, frozen: true,
            preserveExpanded: row.preserveExpanded || preserveExpanded,
            message: preserveExpanded ? { ...message, collapsed: false } : message,
          };
        }),
      };
    });
    const state = get();
    const link = state.streamHistoryLinks[streamId];
    if (link) state.linkStreamHistory(streamId, Number(link.split(":")[1]));
  },

  reconcileCanonicalTail: (canonicalCutoff) => set((state) => {
    const liveRows = state.liveRows.filter((row) =>
      row.version > canonicalCutoff || Boolean(state.streamHistoryLinks[row.id]));
    const remainingIds = new Set(liveRows.map((row) => row.id));
    const rowHeights = { ...state.rowHeights };
    for (const row of state.liveRows) {
      if (!remainingIds.has(row.id)) delete rowHeights[row.id];
    }
    const pendingStreamFinishes = Object.fromEntries(
      Object.entries(state.pendingStreamFinishes).filter(([id]) => remainingIds.has(id)),
    );
    return { liveRows, rowHeights, pendingStreamFinishes };
  }),

  clearLive: () => set((state) => {
    const rowHeights = { ...state.rowHeights };
    for (const row of state.liveRows) delete rowHeights[row.id];
    return {
      liveRows: [], currentStreamId: null, liveVersion: 0, rowHeights,
      pendingStreamFinishes: {}, streamHistoryLinks: {},
    };
  }),
  setProcessing: (processing) => set({ processing }),
  setDraft: (draftHtml, draftText) => set({ draftHtml, draftText }),

  addPendingMessage: (clientMessageId, content) => set((state) => ({
    pendingMessages: {
      ...state.pendingMessages,
      [clientMessageId]: { content, timestamp: Date.now() },
    },
  })),

  removePendingMessages: (ids) => set((state) => {
    if (!ids.length) return state;
    const pendingMessages = { ...state.pendingMessages };
    for (const id of ids) delete pendingMessages[id];
    return { pendingMessages };
  }),
  clearPendingMessages: () => set({ pendingMessages: {} }),
  setFollowMode: (followMode) => set({ followMode }),
  setVisibleRange: (visibleRange) => set({ visibleRange }),
  setScrollMetrics: (scrollMetrics) => set((state) => {
    const previous = state.scrollMetrics;
    if (
      Math.abs(previous.scrollTop - scrollMetrics.scrollTop) < MINIMAP_MEASUREMENT_EPSILON_PX
      && Math.abs(previous.scrollHeight - scrollMetrics.scrollHeight) < MINIMAP_MEASUREMENT_EPSILON_PX
      && Math.abs(previous.viewportHeight - scrollMetrics.viewportHeight) < MINIMAP_MEASUREMENT_EPSILON_PX
    ) return state;
    return { scrollMetrics };
  }),
  mergeRowHeights: (entries) => set((state) => {
    let changed = false;
    const rowHeights = { ...state.rowHeights };
    for (const entry of entries) {
      if (!entry.id || !Number.isFinite(entry.height) || entry.height <= 0) continue;
      if (Math.abs((rowHeights[entry.id] ?? 0) - entry.height) < MINIMAP_MEASUREMENT_EPSILON_PX) continue;
      rowHeights[entry.id] = entry.height;
      changed = true;
    }
    return changed ? { rowHeights } : state;
  }),
  removeRowHeights: (ids) => set((state) => {
    let changed = false;
    const rowHeights = { ...state.rowHeights };
    for (const id of ids) {
      if (id in rowHeights) {
        delete rowHeights[id];
        changed = true;
      }
    }
    return changed ? { rowHeights } : state;
  }),
  setAtBottom: (atBottom) => set({ atBottom }),
  beginUserHeightMutation: () => set({ userHeightMutation: true }),
  finishUserHeightMutation: (atBottom) => set({
    userHeightMutation: false,
    atBottom,
    followMode: atBottom ? "following" : "detached",
  }),
  setResourcesLoading: (resourcesLoading) => set({ resourcesLoading }),
  setResources: (resources) => set({ resources, resourcesError: null }),
  setResourcesError: (resourcesError) => set({ resourcesError }),
}));

export function resetChatRuntimeStoreForTest(): void {
  useChatRuntimeStore.getState().resetSession();
}
