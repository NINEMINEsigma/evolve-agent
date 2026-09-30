import { create } from "zustand";
import type {
  ChatMessage,
  MainSessionActivitySnapshot,
  MainSessionActivitySource,
  MessageContent,
  SessionRuntimeStatus,
  ToolCardResult,
} from "../../types";
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
import { mergeToolCard, toolCardLiveId } from "./toolCards";

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
  mainSessionActivity: MainSessionActivitySnapshot | null;
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
  mergeHistoryPage: (messages: ChatMessage[], startIndex: number, endIndex: number) => void;
  toggleMessageCollapse: (id: string, source: "history" | "live") => void;
  linkStreamHistory: (streamId: string, historyIndex: number) => void;
  linkLiveHistory: (liveId: string, historyRowId: string) => void;
  promoteMappedLiveRows: () => void;
  setPageError: (error: ChatHistoryPageError | null) => void;
  clearCanonicalContent: () => void;
  setInitialReady: (ready: boolean) => void;
  appendLiveMessage: (message: ChatMessage, streaming?: boolean) => number;
  upsertLiveToolCall: (toolCallId: string, toolName: string | undefined, args: Record<string, unknown> | undefined, characterName?: string) => void;
  completeLiveToolCall: (toolCallId: string, toolName: string | undefined, result: ToolCardResult, characterName?: string) => void;
  applyStreamBatch: (batch: StreamBatch) => void;
  queueStreamFinish: (streamId: string, content?: string, metrics?: import("../../types").MessageMetrics, finishReason?: string) => void;
  finishStream: (streamId: string, content?: string, metrics?: import("../../types").MessageMetrics, visibleAtFinish?: boolean, finishReason?: string) => void;
  reconcileCanonicalTail: () => void;
  clearLive: () => void;
  beginOptimisticMainSessionActivity: (localId: string, source: MainSessionActivitySource) => void;
  placeProvisionalActivityAfterUser: () => void;
  reconcileMainSessionActivity: (status: SessionRuntimeStatus) => void;
  clearMainSessionActivityPlaceholders: () => void;
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
  mainSessionActivity: null as MainSessionActivitySnapshot | null,
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

const historyRowMatchesLive = (history: ChatMessage, live: LiveChatRow, historyId: string): boolean => {
  if (history.toolCard || live.message.toolCard) {
    return history.role === "tool"
      && live.message.role === "tool"
      && history.toolCard?.request.toolCallId === live.message.toolCard?.request.toolCallId;
  }
  if (history.role !== live.message.role) return false;
  if (historyId.includes(":tool:") && live.message.role !== "tool") return false;
  if (history.characterName && live.message.characterName
    && history.characterName !== live.message.characterName) return false;
  if (history.role === "assistant") {
    return historyMatchesLive(history, live, historyId);
  }
  if (history.role === "tool" && history.toolName && live.message.toolName
    && history.toolName !== live.message.toolName) return false;
  return true;
};

const skeletonMatchesLive = (skeleton: HistorySkeletonRowDto, live: LiveChatRow): boolean => {
  const expectedRole = skeleton.is_system_status || skeleton.role === "system"
    ? "system"
    : skeleton.row_kind === "tool_card" || skeleton.role === "tool"
      ? "tool"
      : skeleton.role;
  if (skeleton.row_kind === "tool_card" || skeleton.role === "tool") {
    return expectedRole === "tool"
      && live.message.role === "tool"
      && skeleton.tool_call_id === live.message.toolCard?.request.toolCallId;
  }
  if (expectedRole !== live.message.role) return false;
  return true;
};

const activityLiveId = (activityId: string): string => `activity:${activityId}`;

const isSemanticallyEmptyActivityRow = (row: LiveChatRow): boolean => {
  if (!row.activityPlaceholder) return false;
  const message = row.message;
  const contentEmpty = typeof message.content === "string"
    ? message.content.trim().length === 0
    : message.content.length === 0;
  const rawArgsEmpty = !message.toolArgsRawMap
    || Object.values(message.toolArgsRawMap).every((value) => !value);
  return contentEmpty
    && !message.reasoningContent?.trim()
    && !message.toolName
    && !message.toolArgs
    && rawArgsEmpty
    && !message.toolCard
    && !message.imageMarkdown
    && !message.downloadInfo
    && !message.isSystemStatus;
};

type ActivityStreamState = Pick<
  ChatRuntimeState,
  | "liveRows"
  | "rowHeights"
  | "streamHistoryLinks"
  | "pendingStreamFinishes"
  | "currentStreamId"
  | "mainSessionActivity"
>;

const resolveActivityStreamRow = (
  state: ActivityStreamState,
  streamId: string,
  characterName: string | undefined,
  version: number,
): ActivityStreamState => {
  const exact = state.liveRows.find((row) => row.id === streamId);
  if (exact) {
    return {
      ...state,
      currentStreamId: streamId,
      liveRows: state.liveRows.map((row) => row.id === streamId
        ? {
            ...row,
            activityId: state.mainSessionActivity?.activity_id ?? row.activityId,
            provisional: state.mainSessionActivity ? false : row.provisional,
            message: {
              ...row.message,
              characterName: characterName ?? row.message.characterName,
            },
          }
        : row),
    };
  }

  const activity = state.mainSessionActivity;
  const authoritativeStream = activity?.stream_id || null;
  const canAdoptPlaceholder = !authoritativeStream || authoritativeStream === streamId;
  const candidate = canAdoptPlaceholder
    ? state.liveRows.find((row) => row.activityPlaceholder
        && row.streaming
        && (row.provisional || !activity || row.activityId === activity.activity_id))
    : undefined;

  if (!candidate) {
    const message: ChatMessage = {
      role: "assistant",
      content: "",
      id: streamId,
      characterName: characterName ?? activity?.character_name ?? undefined,
    };
    return {
      ...state,
      currentStreamId: streamId,
      liveRows: [...state.liveRows, {
        id: streamId,
        version,
        message,
        streaming: true,
        frozen: false,
        activityId: activity?.activity_id,
        activityPlaceholder: Boolean(activity),
        provisional: false,
      }],
    };
  }

  const oldId = candidate.id;
  const rowHeights = { ...state.rowHeights };
  if (rowHeights[oldId] !== undefined) {
    rowHeights[streamId] = rowHeights[oldId];
    delete rowHeights[oldId];
  }
  const streamHistoryLinks = { ...state.streamHistoryLinks };
  if (streamHistoryLinks[oldId] !== undefined) {
    streamHistoryLinks[streamId] = streamHistoryLinks[oldId];
    delete streamHistoryLinks[oldId];
  }
  const pendingStreamFinishes = { ...state.pendingStreamFinishes };
  if (pendingStreamFinishes[oldId] !== undefined) {
    pendingStreamFinishes[streamId] = {
      ...pendingStreamFinishes[oldId],
      streamId,
    };
    delete pendingStreamFinishes[oldId];
  }
  return {
    ...state,
    currentStreamId: streamId,
    rowHeights,
    streamHistoryLinks,
    pendingStreamFinishes,
    liveRows: state.liveRows.map((row) => row.id === oldId
      ? {
          ...row,
          id: streamId,
          activityId: activity?.activity_id ?? row.activityId,
          provisional: false,
          message: {
            ...row.message,
            id: streamId,
            characterName: characterName ?? activity?.character_name ?? row.message.characterName,
          },
        }
      : row),
  };
};

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

  mergeHistoryPage: (messages, startIndex, endIndex) => set((state) => {
    const contentByRowId = { ...state.contentByRowId };
    const transferred = new Set<string>();
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    for (const message of messages) {
      const previous = contentByRowId[message.id];
      const link = Object.entries(streamHistoryLinks).find(([, rowId]) => rowId === message.id);
      const live = link && state.liveRows.find((row) => row.id === link[0]);
      const matches = Boolean(live && !live.streaming && historyRowMatchesLive(message, live, message.id));
      const transferredCollapse = matches && live?.preserveExpanded ? live.message.collapsed : undefined;
      contentByRowId[message.id] = previous?.collapsed !== undefined
        ? { ...message, collapsed: previous.collapsed }
        : transferredCollapse === undefined ? message : { ...message, collapsed: transferredCollapse };
      if (link && !live) {
        delete streamHistoryLinks[link[0]];
      } else if (link && matches) {
        delete streamHistoryLinks[link[0]];
        transferred.add(link[0]);
      }
    }
    const liveRows = state.liveRows.filter((row) => !transferred.has(row.id));
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

  linkLiveHistory: (liveId, historyRowId) => set((state) => {
    if (!liveId || !historyRowId) return state;
    const existingLink = state.streamHistoryLinks[liveId];
    if (existingLink && existingLink !== historyRowId) {
      console.error("实时消息正典映射冲突", { liveId, existingLink, historyRowId });
      return state;
    }
    return existingLink
      ? state
      : { streamHistoryLinks: { ...state.streamHistoryLinks, [liveId]: historyRowId } };
  }),

  promoteMappedLiveRows: () => set((state) => {
    const contentByRowId = { ...state.contentByRowId };
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    const transferred = new Set<string>();
    const rowHeights = { ...state.rowHeights };
    for (const [liveId, historyId] of Object.entries(streamHistoryLinks)) {
      const skeleton = state.skeleton.find((row) => row.row_id === historyId);
      const live = state.liveRows.find((row) => row.id === liveId);
      if (!skeleton || !live || live.streaming) continue;
      if (!skeletonMatchesLive(skeleton, live)) {
        console.error("实时消息与正典骨架身份不匹配", { liveId, historyId });
        continue;
      }
      const current = contentByRowId[historyId];
      if (current && !historyRowMatchesLive(current, live, historyId)) {
        console.error("实时消息正典目标身份不匹配", { liveId, historyId });
        continue;
      }
      contentByRowId[historyId] = current || {
        ...live.message,
        id: historyId,
        messageIndex: skeleton.history_index,
        isSystemStatus: skeleton.is_system_status || live.message.isSystemStatus,
      };
      delete streamHistoryLinks[liveId];
      transferred.add(liveId);
      delete rowHeights[liveId];
    }
    if (!transferred.size) return state;
    const pendingStreamFinishes = Object.fromEntries(
      Object.entries(state.pendingStreamFinishes).filter(([id]) => !transferred.has(id)),
    );
    return {
      contentByRowId,
      streamHistoryLinks,
      liveRows: state.liveRows.filter((row) => !transferred.has(row.id)),
      pendingStreamFinishes,
      rowHeights,
    };
  }),

  linkStreamHistory: (streamId, historyIndex) => {
    if (!streamId || !Number.isSafeInteger(historyIndex) || historyIndex < 0) return;
    get().linkLiveHistory(streamId, `history:${historyIndex}:message`);
    get().promoteMappedLiveRows();
  },

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

  upsertLiveToolCall: (toolCallId, toolName, args, characterName) => set((state) => {
    if (!toolCallId) return state;
    const id = toolCardLiveId(toolCallId);
    const index = state.liveRows.findIndex((row) => row.id === id);
    const current = index >= 0 ? state.liveRows[index] : undefined;
    const toolCard = mergeToolCard(current?.message.toolCard, {
      status: "running",
      request: { toolCallId, toolName, args },
    });
    const message: ChatMessage = {
      ...(current?.message || { id, role: "tool", content: "" }),
      id,
      role: "tool",
      content: `${characterName ? `${characterName} ` : ""}⚡ ${toolName || "tool"}`,
      toolName: toolName || current?.message.toolName,
      toolArgs: args || current?.message.toolArgs,
      characterName: characterName || current?.message.characterName,
      toolCard,
    };
    const version = state.liveVersion + (current ? 1 : 1);
    const row: LiveChatRow = {
      id,
      version,
      message,
      streaming: false,
      frozen: false,
    };
    return {
      liveVersion: version,
      liveRows: current
        ? state.liveRows.map((item, itemIndex) => itemIndex === index ? { ...item, ...row } : item)
        : [...state.liveRows, row],
    };
  }),

  completeLiveToolCall: (toolCallId, toolName, result, characterName) => set((state) => {
    if (!toolCallId) return state;
    const id = toolCardLiveId(toolCallId);
    const status = result.isError ? "failed" : "succeeded";
    const index = state.liveRows.findIndex((row) => row.id === id);
    const current = index >= 0 ? state.liveRows[index] : undefined;
    const existingCard = current?.message.toolCard;
    const toolCard = mergeToolCard(existingCard, {
      status,
      request: { toolCallId, toolName },
      result,
    });
    const message: ChatMessage = {
      ...(current?.message || { id, role: "tool", content: result.content }),
      id,
      role: "tool",
      content: result.content,
      toolName: toolName || current?.message.toolName,
      characterName: characterName || current?.message.characterName,
      toolCard,
      toolCallMeta: result.toolCallMeta,
      imageMarkdown: result.imageMarkdown,
      downloadInfo: result.downloadInfo,
      isError: result.isError,
    };
    const liveRows = current
      ? state.liveRows.map((item, itemIndex) => itemIndex === index
        ? { ...item, message, streaming: false, frozen: true, version: state.liveVersion + 1 }
        : item)
      : [...state.liveRows, { id, version: state.liveVersion + 1, message, streaming: false, frozen: true }];
    const link = state.streamHistoryLinks[id];
    const contentByRowId = { ...state.contentByRowId };
    if (link) {
      const canonical = contentByRowId[link];
      contentByRowId[link] = canonical
        ? { ...canonical, ...message, id: link, toolCard }
        : { ...message, id: link };
    }
    return { liveRows, contentByRowId, liveVersion: state.liveVersion + 1 };
  }),

  beginOptimisticMainSessionActivity: (localId, source) => set((state) => {
    if (state.mainSessionActivity || state.liveRows.some(
      (row) => row.streaming && row.message.role === "assistant",
    )) {
      return state.processing ? state : { processing: true };
    }
    const activityId = `local:${localId}`;
    const id = activityLiveId(activityId);
    const version = state.liveVersion + 1;
    const snapshot: MainSessionActivitySnapshot = {
      activity_id: activityId,
      revision: 0,
      source,
      phase: "queued",
      stream_id: null,
      character_name: null,
    };
    return {
      mainSessionActivity: snapshot,
      processing: true,
      liveVersion: version,
      liveRows: [...state.liveRows, {
        id,
        version,
        message: { role: "assistant", content: "", id },
        streaming: true,
        frozen: false,
        activityId,
        activityPlaceholder: true,
        provisional: true,
      }],
    };
  }),

  placeProvisionalActivityAfterUser: () => set((state) => {
    const provisionalRows = state.liveRows.filter(
      (row) => row.provisional && row.activityPlaceholder,
    );
    if (!provisionalRows.length) return state;
    const remainingRows = state.liveRows.filter(
      (row) => !(row.provisional && row.activityPlaceholder),
    );
    let lastUserIndex = -1;
    remainingRows.forEach((row, index) => {
      if (row.message.role === "user") lastUserIndex = index;
    });
    if (lastUserIndex < 0) return state;
    remainingRows.splice(lastUserIndex + 1, 0, ...provisionalRows);
    return { liveRows: remainingRows, liveVersion: state.liveVersion + 1 };
  }),

  reconcileMainSessionActivity: (status) => set((state) => {
    const incoming = status.activity ?? null;
    if (!status.processing && incoming === null) {
      const removedIds = state.liveRows
        .filter(isSemanticallyEmptyActivityRow)
        .map((row) => row.id);
      if (!removedIds.length && !state.mainSessionActivity && !state.processing) return state;
      const removed = new Set(removedIds);
      const rowHeights = { ...state.rowHeights };
      const streamHistoryLinks = { ...state.streamHistoryLinks };
      const pendingStreamFinishes = { ...state.pendingStreamFinishes };
      for (const id of removed) {
        delete rowHeights[id];
        delete streamHistoryLinks[id];
        delete pendingStreamFinishes[id];
      }
      return {
        mainSessionActivity: null,
        processing: false,
        liveRows: state.liveRows.filter((row) => !removed.has(row.id)),
        currentStreamId: state.currentStreamId && removed.has(state.currentStreamId)
          ? null : state.currentStreamId,
        rowHeights,
        streamHistoryLinks,
        pendingStreamFinishes,
        liveVersion: removed.size ? state.liveVersion + 1 : state.liveVersion,
      };
    }
    if (incoming === null) {
      return state.processing === status.processing
        ? state
        : { processing: status.processing };
    }

    const current = state.mainSessionActivity;
    if (
      current
      && current.activity_id === incoming.activity_id
      && current.revision > incoming.revision
    ) {
      return state.processing ? state : { processing: true };
    }
    if (
      current
      && current.activity_id === incoming.activity_id
      && current.revision === incoming.revision
      && current.phase === incoming.phase
      && current.stream_id === incoming.stream_id
      && current.character_name === incoming.character_name
    ) {
      return state.processing ? state : { processing: true };
    }

    let liveRows = state.liveRows;
    let rowHeights = state.rowHeights;
    let streamHistoryLinks = state.streamHistoryLinks;
    let pendingStreamFinishes = state.pendingStreamFinishes;
    const replacingActivity = current
      && !current.activity_id.startsWith("local:")
      && current.activity_id !== incoming.activity_id;
    if (replacingActivity) {
      const removed = new Set(
        liveRows.filter(isSemanticallyEmptyActivityRow).map((row) => row.id),
      );
      liveRows = liveRows.filter((row) => !removed.has(row.id));
      if (removed.size) {
        rowHeights = Object.fromEntries(
          Object.entries(rowHeights).filter(([id]) => !removed.has(id)),
        );
        streamHistoryLinks = Object.fromEntries(
          Object.entries(streamHistoryLinks).filter(([id]) => !removed.has(id)),
        );
        pendingStreamFinishes = Object.fromEntries(
          Object.entries(pendingStreamFinishes).filter(([id]) => !removed.has(id)),
        );
      }
    }
    const provisional = liveRows.find((row) => row.provisional && row.activityPlaceholder);
    if (provisional) {
      liveRows = liveRows.map((row) => row.id === provisional.id
        ? { ...row, activityId: incoming.activity_id, provisional: false }
        : row);
    }

    let next: ActivityStreamState = {
      liveRows,
      rowHeights,
      streamHistoryLinks,
      pendingStreamFinishes,
      currentStreamId: state.currentStreamId,
      mainSessionActivity: incoming,
    };

    if (incoming.stream_id) {
      next = resolveActivityStreamRow(
        next,
        incoming.stream_id,
        incoming.character_name ?? undefined,
        state.liveVersion + 1,
      );
    } else if (incoming.phase === "queued" || incoming.phase === "preparing") {
      const existing = next.liveRows.find((row) => row.activityPlaceholder
        && row.activityId === incoming.activity_id);
      if (!existing) {
        const id = activityLiveId(incoming.activity_id);
        next = {
          ...next,
          liveRows: [...next.liveRows, {
            id,
            version: state.liveVersion + 1,
            message: {
              role: "assistant",
              content: "",
              id,
              characterName: incoming.character_name ?? undefined,
            },
            streaming: true,
            frozen: false,
            activityId: incoming.activity_id,
            activityPlaceholder: true,
            provisional: false,
          }],
        };
      }
    } else {
      const removed = new Set(
        next.liveRows
          .filter((row) => row.activityId === incoming.activity_id
            && isSemanticallyEmptyActivityRow(row))
          .map((row) => row.id),
      );
      if (removed.size) {
        next = {
          ...next,
          liveRows: next.liveRows.filter((row) => !removed.has(row.id)),
          rowHeights: Object.fromEntries(
            Object.entries(next.rowHeights).filter(([id]) => !removed.has(id)),
          ),
          streamHistoryLinks: Object.fromEntries(
            Object.entries(next.streamHistoryLinks).filter(([id]) => !removed.has(id)),
          ),
          pendingStreamFinishes: Object.fromEntries(
            Object.entries(next.pendingStreamFinishes).filter(([id]) => !removed.has(id)),
          ),
          currentStreamId: next.currentStreamId && removed.has(next.currentStreamId)
            ? null : next.currentStreamId,
        };
      }
    }

    return {
      ...next,
      processing: true,
      liveVersion: state.liveVersion + 1,
    };
  }),

  clearMainSessionActivityPlaceholders: () => set((state) => {
    const removedIds = state.liveRows
      .filter(isSemanticallyEmptyActivityRow)
      .map((row) => row.id);
    const removed = new Set(removedIds);
    const rowHeights = { ...state.rowHeights };
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    const pendingStreamFinishes = { ...state.pendingStreamFinishes };
    for (const id of removed) {
      delete rowHeights[id];
      delete streamHistoryLinks[id];
      delete pendingStreamFinishes[id];
    }
    return {
      mainSessionActivity: null,
      processing: false,
      liveRows: state.liveRows.filter((row) => !removed.has(row.id)),
      currentStreamId: state.currentStreamId && removed.has(state.currentStreamId)
        ? null : state.currentStreamId,
      rowHeights,
      streamHistoryLinks,
      pendingStreamFinishes,
      liveVersion: removed.size ? state.liveVersion + 1 : state.liveVersion,
    };
  }),

  applyStreamBatch: (batch) => set((state) => {
    const version = state.liveVersion + 1;
    const resolved = resolveActivityStreamRow(
      state,
      batch.streamId,
      batch.characterName,
      version,
    );
    const existing = resolved.liveRows.find((row) => row.id === batch.streamId);
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
    return {
      ...resolved,
      liveRows: resolved.liveRows.map((row) => row.id === batch.streamId
        ? { ...row, version, message: nextMessage, streaming: true, frozen: false }
        : row),
      liveVersion: version,
      currentStreamId: batch.streamId,
      processing: true,
    };
  }),

  queueStreamFinish: (streamId, content, metrics, finishReason) => set((state) => {
    const live = state.liveRows.find((row) => row.id === streamId && row.streaming);
    if (!live || state.pendingStreamFinishes[streamId]) return state;
    return {
      pendingStreamFinishes: {
        ...state.pendingStreamFinishes,
        [streamId]: { streamId, content, metrics, finishReason },
      },
      liveRows: state.liveRows.map((row) => row.id === streamId
        ? { ...row, message: { ...row.message, content: content || row.message.content } }
        : row),
    };
  }),

  finishStream: (streamId, content, metrics, visibleAtFinish = false, finishReason) => {
    set((state) => {
      const queuedFinish = state.pendingStreamFinishes[streamId];
      const effectiveFinishReason = finishReason ?? queuedFinish?.finishReason ?? "stop";
      const pendingStreamFinishes = { ...state.pendingStreamFinishes };
      delete pendingStreamFinishes[streamId];
      const existing = state.liveRows.find((row) => row.id === streamId);
      if (!existing && !state.pendingStreamFinishes[streamId]) return state;
      const version = state.pendingStreamFinishes[streamId]
        ? (existing?.version ?? state.liveVersion) : state.liveVersion + 1;
      const nextLiveRows: LiveChatRow[] = [];
      const rowHeights = { ...state.rowHeights };
      const streamHistoryLinks = { ...state.streamHistoryLinks };
      for (const row of state.liveRows) {
        if (row.id !== streamId) {
          nextLiveRows.push(row);
          continue;
        }
        const message = {
          ...row.message,
          content: content || row.message.content,
          reasoningDuration: metrics?.reasoning_duration_ms ?? row.message.reasoningDuration,
          contentDuration: metrics?.content_duration_ms ?? row.message.contentDuration,
          completionTokens: metrics?.completion_tokens ?? row.message.completionTokens,
          tokensPerSecond: metrics?.tokens_per_second ?? row.message.tokensPerSecond,
        };
        const completedRow: LiveChatRow = { ...row, message };
        const removeEmptyActivityStream = effectiveFinishReason.length > 0
          && isSemanticallyEmptyActivityRow(completedRow);
        if (removeEmptyActivityStream) {
          delete rowHeights[row.id];
          delete streamHistoryLinks[row.id];
          continue;
        }
        const text = typeof message.content === "string" ? message.content.trim() : "";
        const hasToolParameterStream = Boolean(message.toolName || message.toolArgs || message.toolArgsRawMap);
        const removeInvisibleToolStream = message.role === "assistant"
          && !text
          && !message.reasoningContent?.trim()
          && !message.isSystemStatus
          && hasToolParameterStream;
        if (removeInvisibleToolStream) {
          delete rowHeights[row.id];
          delete streamHistoryLinks[row.id];
          continue;
        }
        const preserveExpanded = row.streaming && visibleAtFinish
          && message.role === "assistant" && !message.isSystemStatus
          && isLongChatMessage(message) && !row.collapseManuallyChanged;
        nextLiveRows.push({
          ...row, version, streaming: false, frozen: true,
          activityPlaceholder: false,
          provisional: false,
          preserveExpanded: row.preserveExpanded || preserveExpanded,
          message: preserveExpanded ? { ...message, collapsed: false } : message,
        });
      }
      return {
        pendingStreamFinishes,
        liveVersion: state.pendingStreamFinishes[streamId] ? state.liveVersion : version,
        currentStreamId: state.currentStreamId === streamId ? null : state.currentStreamId,
        liveRows: nextLiveRows,
        rowHeights,
        streamHistoryLinks,
      };
    });
    const state = get();
    const link = state.streamHistoryLinks[streamId];
    if (link) state.linkStreamHistory(streamId, Number(link.split(":")[1]));
  },

  reconcileCanonicalTail: () => {
    get().promoteMappedLiveRows();
  },

  clearLive: () => set((state) => {
    const rowHeights = { ...state.rowHeights };
    for (const row of state.liveRows) delete rowHeights[row.id];
    return {
      liveRows: [], currentStreamId: null, liveVersion: 0, rowHeights,
      pendingStreamFinishes: {}, streamHistoryLinks: {},
      mainSessionActivity: null, processing: false,
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
