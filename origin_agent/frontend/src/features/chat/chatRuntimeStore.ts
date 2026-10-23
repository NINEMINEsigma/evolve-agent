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
  ChatRenderRow,
  ChatScrollMetrics,
  ChatVisibleRange,
  HistoryResourcesResponseDto,
  HistorySkeletonRowDto,
  LiveChatRow,
  PendingChatMessage,
  PendingStreamFinish,
  RegenerateTrimPayload,
  StreamBatch,
} from "./types";
import { generateUUID } from "../../utils";
import { CHAT_MEASUREMENT_EPSILON_PX } from "../../constants/history";
import { isLongChatMessage } from "./messageCollapse";
import { mergeToolCard, toolCardLiveId } from "./toolCards";
import { STORAGE_KEYS } from "../../constants/storage";
import { isMessageVisible } from "./messageVisibility";

export interface ChatRuntimeState {
  showSystemUserMessages: boolean;
  setShowSystemUserMessages: (show: boolean) => void;
  sessionId: string;
  generation: number;
  historyReloadRequired: boolean;
  invalidateHistory: (sessionId: string, liveCutoffVersion?: number) => number;
  applyHistoryReload: (
    rows: HistorySkeletonRowDto[], historyCount: number, messages: ChatMessage[],
    startIndex: number, endIndex: number, generation: number,
  ) => void;
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
  canonicalHandoffReady: boolean;
  pendingHistoryPages: Array<{ messages: ChatMessage[]; startIndex: number; endIndex: number }>;
  streamHistoryLinks: Record<string, string>;
  liveVersion: number;
  currentStreamId: string | null;
  processing: boolean;
  requireToolCall: boolean;
  setRequireToolCall: (enabled: boolean) => void;
  clearRequireToolCall: (sessionId: string) => void;
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
  trimHistoryForRegeneration: (trim: RegenerateTrimPayload) => number;
  cancelOptimisticMainSessionActivity: (activityId: string) => void;
  setSkeletonLoading: (loading: boolean) => void;
  setSkeletonError: (error: string | null) => void;
  replaceSkeleton: (rows: HistorySkeletonRowDto[], historyCount: number) => void;
  appendSkeleton: (rows: HistorySkeletonRowDto[], historyCount: number) => void;
  mergeHistoryPage: (messages: ChatMessage[], startIndex: number, endIndex: number, immediate?: boolean) => void;
  toggleMessageCollapse: (id: string) => void;
  linkStreamHistory: (streamId: string, historyIndex: number) => void;
  linkLiveHistory: (liveId: string, historyRowId: string) => void;
  promoteMappedLiveRows: () => void;
  setPageError: (error: ChatHistoryPageError | null) => void;
  clearCanonicalContent: () => void;
  setInitialReady: (ready: boolean) => void;
  appendLiveMessage: (message: ChatMessage, streaming?: boolean) => number;
  upsertLiveToolCall: (toolCallId: string, toolName: string | undefined, args: Record<string, unknown> | undefined, characterName?: string) => void;
  completeLiveToolCall: (toolCallId: string, toolName: string | undefined, result: ToolCardResult, characterName?: string) => void;
  discardLiveToolCalls: (toolCallIds: string[], sessionId: string) => void;
  applyStreamBatch: (batch: StreamBatch) => void;
  queueStreamFinish: (streamId: string, content?: string, metrics?: import("../../types").MessageMetrics, finishReason?: string) => void;
  setCanonicalHandoffReady: (ready: boolean) => void;
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
  historyReloadRequired: false,
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
  canonicalHandoffReady: true,
  pendingHistoryPages: [] as Array<{ messages: ChatMessage[]; startIndex: number; endIndex: number }>,
  streamHistoryLinks: {} as Record<string, string>,
  liveVersion: 0,
  currentStreamId: null as string | null,
  processing: false,
  requireToolCall: false,
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

export function selectChatRenderRows(state: ChatRuntimeState): ChatRenderRow[] {
  const liveByHistoryId = new Map<string, LiveChatRow>();
  const renderedLiveIds = new Set<string>();
  for (const [liveId, historyRowId] of Object.entries(state.streamHistoryLinks)) {
    const live = state.liveRows.find((row) => row.id === liveId);
    if (live) {
      liveByHistoryId.set(historyRowId, live);
    }
  }

  const rows: ChatRenderRow[] = state.skeleton.map((skeleton) => {
    const live = liveByHistoryId.get(skeleton.row_id);
    if (live) renderedLiveIds.add(live.id);
    const canonicalMessage = state.contentByRowId[skeleton.row_id];
    const message = live && live.streaming
      ? live.message
      : canonicalMessage && live?.preserveExpanded && !live.collapseManuallyChanged
        ? { ...canonicalMessage, collapsed: false }
        : canonicalMessage || live?.message || null;
    return {
      renderId: live?.renderId || live?.id || skeleton.row_id,
      historyRowId: skeleton.row_id,
      historyIndex: skeleton.history_index,
      skeleton,
      message,
      streaming: Boolean(live?.streaming),
      frozen: Boolean(live?.frozen),
      canonical: Boolean(canonicalMessage),
      pageError: Object.values(state.pageErrors).find((error) =>
        skeleton.history_index >= error.startIndex && skeleton.history_index < error.endIndex) || null,
      liveId: live?.id || null,
      activityPlaceholder: live?.activityPlaceholder,
      preserveExpanded: live?.preserveExpanded,
    };
  });

  for (const live of state.liveRows) {
    if (renderedLiveIds.has(live.id)) continue;
    rows.push({
      renderId: live.renderId || live.id,
      historyRowId: null,
      historyIndex: null,
      skeleton: null,
      message: live.message,
      streaming: live.streaming,
      frozen: live.frozen,
      canonical: false,
      pageError: null,
      liveId: live.id,
      activityPlaceholder: live.activityPlaceholder,
      preserveExpanded: live.preserveExpanded,
    });
  }
  return rows.filter((row) => isMessageVisible(
    row.skeleton?.role ?? row.message?.role ?? "",
    row.skeleton ? row.skeleton.character_name : row.message?.characterName,
    state.showSystemUserMessages,
  ));
}

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
        renderId: streamId,
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
          renderId: candidate.renderId || oldId,
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

function readShowSystemUserMessages(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.SHOW_SYSTEM_USER_MESSAGES) !== "false";
  } catch {
    return true;
  }
}

export const useChatRuntimeStore = create<ChatRuntimeState>((set, get) => ({
  ...initialState,
  // 全局显示偏好不放入 initialState，切换或重置会话时保留。
  showSystemUserMessages: readShowSystemUserMessages(),
  setShowSystemUserMessages: (showSystemUserMessages) => {
    try {
      localStorage.setItem(STORAGE_KEYS.SHOW_SYSTEM_USER_MESSAGES, String(showSystemUserMessages));
    } catch {
      // 浏览器存储不可用时，本次页面内的切换仍然生效。
    }
    set({ showSystemUserMessages });
  },

  beginSession: (sessionId) => {
    const nextGeneration = get().generation + 1;
    set((state) => ({
      ...initialState,
      sessionId,
      generation: nextGeneration,
      // 同会话历史重建保留当前选择；真正切换或初次进入才关闭。
      requireToolCall: Boolean(state.sessionId) && state.sessionId === sessionId
        ? state.requireToolCall : false,
      loadedHistoryIndices: new Set<number>(),
    }));
    return nextGeneration;
  },

  resetSession: () => {
    const nextGeneration = get().generation + 1;
    set({ ...initialState, generation: nextGeneration, loadedHistoryIndices: new Set<number>() });
  },

  trimHistoryForRegeneration: (trim) => {
    const state = get();
    const skeleton = state.skeleton.filter((row) => row.history_index < trim.keep_count);
    const skeletonById = new Map(skeleton.map((row) => [row.row_id, row]));
    const invalidToolRows = new Set<string>();
    const invalidToolIndices = new Set<number>();
    const hasRetainedResultIndex = (index: number | undefined): boolean => (
      index !== undefined && Number.isSafeInteger(index) && index >= 0 && index < trim.keep_count
    );
    const withUpdatedSuffix = (message: ChatMessage, row: HistorySkeletonRowDto): ChatMessage => (
      row.row_kind === "message" && row.role === "user" && row.history_index === trim.message_index
        ? {
            ...message,
            messageSuffix: trim.message_suffix ?? undefined,
            dynamicMessageSuffix: trim.dynamic_message_suffix ?? undefined,
          }
        : message
    );

    for (const row of skeleton) {
      if (row.row_kind !== "tool_card") continue;
      const message = state.contentByRowId[row.row_id];
      const card = message?.toolCard;
      if (message && (!card || card.request.toolCallId !== row.tool_call_id
        || (card.result && !hasRetainedResultIndex(card.result.historyIndex)))) {
        invalidToolRows.add(row.row_id);
      }
    }
    for (const live of state.liveRows) {
      const historyRowId = state.streamHistoryLinks[live.id];
      const row = skeletonById.get(historyRowId);
      if (!row || row.row_kind !== "tool_card") continue;
      const card = live.message.toolCard;
      const canonicalCard = state.contentByRowId[row.row_id]?.toolCard;
      if (!card || !row.tool_call_id || card.request.toolCallId !== row.tool_call_id
        || live.id !== toolCardLiveId(row.tool_call_id)) {
        invalidToolRows.add(row.row_id);
        continue;
      }
      // 实时工具结果通常没有索引，只能从同一调用的正典结果取得范围证据。
      if (card.result) {
        const resultIndex = card.result.historyIndex ?? (
          canonicalCard?.request.toolCallId === card.request.toolCallId
            ? canonicalCard.result?.historyIndex
            : undefined
        );
        if (!hasRetainedResultIndex(resultIndex)) invalidToolRows.add(row.row_id);
      }
    }

    const contentByRowId: Record<string, ChatMessage> = {};
    for (const row of skeleton) {
      if (invalidToolRows.has(row.row_id)) {
        invalidToolIndices.add(row.history_index);
        continue;
      }
      const message = state.contentByRowId[row.row_id];
      if (message) contentByRowId[row.row_id] = withUpdatedSuffix(message, row);
    }

    const liveRows: LiveChatRow[] = [];
    const streamHistoryLinks: Record<string, string> = {};
    let keptActivityPlaceholder = false;
    for (const live of state.liveRows) {
      const historyRowId = state.streamHistoryLinks[live.id];
      const row = skeletonById.get(historyRowId);
      if (row && !invalidToolRows.has(row.row_id)) {
        liveRows.push({ ...live, message: withUpdatedSuffix(live.message, row) });
        streamHistoryLinks[live.id] = row.row_id;
      } else if (!keptActivityPlaceholder && state.mainSessionActivity
        && live.activityId === state.mainSessionActivity.activity_id
        && live.message.role === "assistant" && isSemanticallyEmptyActivityRow(live)) {
        liveRows.push(live);
        keptActivityPlaceholder = true;
      }
    }
    const retainedLiveIds = new Set(liveRows.map((row) => row.id));
    const pendingStreamFinishes = Object.fromEntries(
      Object.entries(state.pendingStreamFinishes).filter(([id]) => retainedLiveIds.has(id)),
    );
    const generation = state.generation + 1;
    const nextState: ChatRuntimeState = {
      ...state,
      generation,
      skeleton,
      knownHistoryCount: trim.keep_count,
      lastUserHistoryIndex: trim.message_index,
      contentByRowId,
      liveRows,
      streamHistoryLinks,
      pendingStreamFinishes,
      currentStreamId: state.currentStreamId && retainedLiveIds.has(state.currentStreamId)
        ? state.currentStreamId : null,
      loadedHistoryIndices: new Set([...state.loadedHistoryIndices].filter(
        (index) => index < trim.keep_count && !invalidToolIndices.has(index),
      )),
      pendingHistoryPages: [],
      pageErrors: {},
      skeletonError: null,
      skeletonLoading: false,
      resources: null,
      resourcesLoading: false,
      resourcesError: null,
      liveVersion: state.liveVersion + 1,
      canonicalHandoffReady: false,
      processing: true,
      followMode: state.followMode === "returning" ? "detached" : state.followMode,
    };
    const renderRows = selectChatRenderRows(nextState);
    const retainedRenderIds = new Set(renderRows.map((row) => row.renderId));
    nextState.rowHeights = Object.fromEntries(
      Object.entries(state.rowHeights).filter(([id]) => retainedRenderIds.has(id)),
    );
    const lastRow = Math.max(0, renderRows.length - 1);
    const startIndex = Math.max(0, Math.min(state.visibleRange.startIndex, lastRow));
    nextState.visibleRange = {
      startIndex,
      endIndex: Math.max(startIndex, Math.min(state.visibleRange.endIndex, lastRow)),
    };
    // 只提交一次，避免旧映射、旧正文与新骨架在中间状态混用。
    set(nextState);
    return generation;
  },

  cancelOptimisticMainSessionActivity: (activityId) => set((state) => {
    if (!activityId.startsWith("local:") || state.mainSessionActivity?.activity_id !== activityId) {
      return state;
    }
    const activityRows = state.liveRows.filter((row) => row.activityId === activityId);
    if (activityRows.some((row) => !row.provisional || !isSemanticallyEmptyActivityRow(row))
      || state.liveRows.some((row) => row.streaming && row.message.role === "assistant"
        && row.activityId !== activityId)) {
      return state;
    }
    const removedIds = new Set(activityRows.map((row) => row.id));
    const removedRenderIds = new Set(activityRows.map((row) => row.renderId || row.id));
    return {
      mainSessionActivity: null,
      processing: false,
      liveRows: state.liveRows.filter((row) => !removedIds.has(row.id)),
      currentStreamId: state.currentStreamId && removedIds.has(state.currentStreamId)
        ? null : state.currentStreamId,
      rowHeights: Object.fromEntries(
        Object.entries(state.rowHeights).filter(([id]) => !removedRenderIds.has(id)),
      ),
      streamHistoryLinks: Object.fromEntries(
        Object.entries(state.streamHistoryLinks).filter(([id]) => !removedIds.has(id)),
      ),
      pendingStreamFinishes: Object.fromEntries(
        Object.entries(state.pendingStreamFinishes).filter(([id]) => !removedIds.has(id)),
      ),
      liveVersion: state.liveVersion + (removedIds.size ? 1 : 0),
    };
  }),

  invalidateHistory: (sessionId, liveCutoffVersion) => {
    const state = get();
    if (!sessionId || state.sessionId !== sessionId) return state.generation;
    const cutoff = liveCutoffVersion ?? state.liveVersion;
    const liveRows = state.liveRows.filter((row) => row.version > cutoff);
    const freshIds = new Set(liveRows.map((row) => row.id));
    const freshRenderIds = new Set(liveRows.map((row) => row.renderId || row.id));
    const generation = state.generation + 1;
    const streamingRows = liveRows.filter((row) => row.streaming);
    set({
      generation,
      historyReloadRequired: true,
      skeleton: [],
      knownHistoryCount: 0,
      lastUserHistoryIndex: -1,
      skeletonLoading: true,
      skeletonError: null,
      contentByRowId: {},
      loadedHistoryIndices: new Set<number>(),
      pageErrors: {},
      pendingHistoryPages: [],
      initialReady: false,
      liveRows,
      streamHistoryLinks: Object.fromEntries(
        Object.entries(state.streamHistoryLinks).filter(([id]) => freshIds.has(id)),
      ),
      pendingStreamFinishes: Object.fromEntries(
        Object.entries(state.pendingStreamFinishes).filter(([id]) => freshIds.has(id)),
      ),
      rowHeights: Object.fromEntries(
        Object.entries(state.rowHeights).filter(([id]) => freshRenderIds.has(id)),
      ),
      currentStreamId: streamingRows.length ? streamingRows[streamingRows.length - 1].id : null,
      canonicalHandoffReady: !liveRows.some((row) => row.streaming),
      followMode: state.followMode === "returning" ? "detached" : state.followMode,
      visibleRange: { startIndex: 0, endIndex: 0 },
      scrollMetrics: { scrollTop: 0, scrollHeight: 0, viewportHeight: 0 },
      userHeightMutation: false,
      resources: null,
      resourcesLoading: false,
      resourcesError: null,
    });
    return generation;
  },

  applyHistoryReload: (skeleton, knownHistoryCount, messages, startIndex, endIndex, generation) => set((state) => {
    if (state.generation !== generation) return state;
    const contentByRowId = Object.fromEntries(messages.map((message) => [message.id, message]));
    const loadedHistoryIndices = new Set<number>();
    for (let index = startIndex; index < endIndex; index += 1) loadedHistoryIndices.add(index);
    // 旧状态已在事件到达时清除；这里绝不能再次清空事件之后收到的实时行与关联。
    return {
      skeleton,
      knownHistoryCount,
      lastUserHistoryIndex: lastUserIndex(skeleton),
      contentByRowId,
      loadedHistoryIndices,
      pageErrors: {},
      initialReady: true,
      skeletonLoading: false,
      skeletonError: null,
      historyReloadRequired: false,
    };
  }),

  setSkeletonLoading: (skeletonLoading) => set({ skeletonLoading }),
  setSkeletonError: (skeletonError) => set({ skeletonError }),

  replaceSkeleton: (skeleton, knownHistoryCount) => set({
    skeleton,
    knownHistoryCount,
    lastUserHistoryIndex: lastUserIndex(skeleton),
    contentByRowId: {},
    // 历史结构边界负责失效旧流；异步骨架不得抹掉新代际已经收到的关联和结束事件。
    loadedHistoryIndices: new Set<number>(),
    pageErrors: {},
  }),

  appendSkeleton: (rows, knownHistoryCount) => set((state) => ({
    skeleton: rows.length ? [...state.skeleton, ...rows] : state.skeleton,
    knownHistoryCount,
    lastUserHistoryIndex: lastUserIndex(rows, state.lastUserHistoryIndex),
  })),

  mergeHistoryPage: (messages, startIndex, endIndex, immediate = false) => set((state) => {
    if (!immediate && !state.canonicalHandoffReady && state.liveRows.length > 0) {
      return {
        pendingHistoryPages: [...state.pendingHistoryPages, { messages, startIndex, endIndex }],
      };
    }
    const contentByRowId = { ...state.contentByRowId };
    for (const message of messages) {
      const previous = contentByRowId[message.id];
      contentByRowId[message.id] = previous?.collapsed !== undefined
        ? { ...message, collapsed: previous.collapsed }
        : message;
    }
    const loadedHistoryIndices = new Set(state.loadedHistoryIndices);
    for (let index = startIndex; index < endIndex; index += 1) loadedHistoryIndices.add(index);
    const pageErrors = Object.fromEntries(
      Object.entries(state.pageErrors).filter(([, error]) =>
        error.endIndex <= startIndex || error.startIndex >= endIndex),
    );
    return { contentByRowId, loadedHistoryIndices, pageErrors };
  }),

  toggleMessageCollapse: (id) => set((state) => {
    const historyMessage = state.contentByRowId[id];
    if (historyMessage) {
      // 正典轨道命中：同步置位关联实时行的 collapseManuallyChanged，
      // 防止 selectChatRenderRows 的 preserveExpanded 分支把手动展开选择回滚。
      const linkedLiveIds = Object.entries(state.streamHistoryLinks)
        .filter(([, historyRowId]) => historyRowId === id)
        .map(([liveId]) => liveId);
      if (linkedLiveIds.length) {
        const liveRows = state.liveRows.map((row) => {
          if (!linkedLiveIds.includes(row.id) || row.collapseManuallyChanged) return row;
          return { ...row, collapseManuallyChanged: true };
        });
        return {
          contentByRowId: {
            ...state.contentByRowId,
            [id]: { ...historyMessage, collapsed: historyMessage.collapsed === false },
          },
          liveRows,
        };
      }
      return {
        contentByRowId: {
          ...state.contentByRowId,
          [id]: { ...historyMessage, collapsed: historyMessage.collapsed === false },
        },
      };
    }
    const index = state.liveRows.findIndex((row) => (row.renderId || row.id) === id || row.id === id);
    if (index < 0) return state;
    const liveRows = [...state.liveRows];
    const row = liveRows[index];
    // 实时轨道命中：若已映射正典且正典内容存在，同步翻转正典折叠，保证渲染读到的
    // 正典消息与实时行一致（覆盖收编行实时 ID 变化的场景）；并终止 preserveExpanded 回滚。
    const linkedHistoryRowId = state.streamHistoryLinks[row.id];
    const contentByRowId = { ...state.contentByRowId };
    const canonicalMessage = linkedHistoryRowId ? contentByRowId[linkedHistoryRowId] : undefined;
    if (canonicalMessage) {
      contentByRowId[linkedHistoryRowId!] = {
        ...canonicalMessage,
        collapsed: row.message.collapsed === false,
      };
    }
    liveRows[index] = {
      ...row,
      message: { ...row.message, collapsed: row.message.collapsed === false },
      collapseManuallyChanged: true,
    };
    return canonicalMessage ? { liveRows, contentByRowId } : { liveRows };
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

  promoteMappedLiveRows: () => set((state) => state),

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
    pendingHistoryPages: [],
    canonicalHandoffReady: true,
    loadedHistoryIndices: new Set<number>(),
    pageErrors: {},
    initialReady: false,
  }),

  setInitialReady: (initialReady) => set({ initialReady }),

  appendLiveMessage: (message, streaming = false) => {
    const version = get().liveVersion + 1;
    set((state) => ({
      liveVersion: version,
      canonicalHandoffReady: false,
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

  discardLiveToolCalls: (toolCallIds, sessionId) => set((state) => {
    // 丢弃事件属于单次流式调用；迟到的跨会话事件不得删除当前会话的实时卡片。
    if (!sessionId || sessionId !== state.sessionId) return state;
    const discarded = new Set(toolCallIds.filter(Boolean).map(toolCardLiveId));
    if (!discarded.size) return state;
    const removed = new Set(
      state.liveRows.filter((row) => discarded.has(row.id)).map((row) => row.id),
    );
    if (!removed.size) return state;
    const rowHeights = { ...state.rowHeights };
    const streamHistoryLinks = { ...state.streamHistoryLinks };
    for (const row of state.liveRows) {
      if (!removed.has(row.id)) continue;
      delete rowHeights[row.renderId || row.id];
      delete streamHistoryLinks[row.id];
    }
    // 正典 History 内容的增删仍由 history_sync 与内容页负责：此处只清实时行及其映射/高度。
    return {
      liveRows: state.liveRows.filter((row) => !removed.has(row.id)),
      rowHeights,
      streamHistoryLinks,
      liveVersion: state.liveVersion + 1,
    };
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
      canonicalHandoffReady: false,
      liveVersion: version,
      liveRows: [...state.liveRows, {
        id,
        renderId: id,
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
            renderId: id,
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
      canonicalHandoffReady: false,
    };
  }),

  setCanonicalHandoffReady: (ready) => {
    const pending = get().pendingHistoryPages;
    set({ canonicalHandoffReady: ready, pendingHistoryPages: ready ? [] : pending });
    if (ready) {
      for (const page of pending) get().mergeHistoryPage(page.messages, page.startIndex, page.endIndex);
    }
  },

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
          delete rowHeights[row.renderId || row.id];
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
          delete rowHeights[row.renderId || row.id];
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
    for (const row of state.liveRows) delete rowHeights[row.renderId || row.id];
    return {
      liveRows: [], currentStreamId: null, liveVersion: 0, rowHeights,
      pendingStreamFinishes: {}, streamHistoryLinks: {},
      mainSessionActivity: null, processing: false,
    };
  }),
  setProcessing: (processing) => set({ processing }),
  setRequireToolCall: (requireToolCall) => set({ requireToolCall }),
  clearRequireToolCall: (sessionId) => {
    if (get().sessionId === sessionId) set({ requireToolCall: false });
  },
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
      Math.abs(previous.scrollTop - scrollMetrics.scrollTop) < CHAT_MEASUREMENT_EPSILON_PX
      && Math.abs(previous.scrollHeight - scrollMetrics.scrollHeight) < CHAT_MEASUREMENT_EPSILON_PX
      && Math.abs(previous.viewportHeight - scrollMetrics.viewportHeight) < CHAT_MEASUREMENT_EPSILON_PX
    ) return state;
    return { scrollMetrics };
  }),
  mergeRowHeights: (entries) => set((state) => {
    let changed = false;
    const rowHeights = { ...state.rowHeights };
    for (const entry of entries) {
      if (!entry.id || !Number.isFinite(entry.height) || entry.height <= 0) continue;
      if (Math.abs((rowHeights[entry.id] ?? 0) - entry.height) < CHAT_MEASUREMENT_EPSILON_PX) continue;
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
