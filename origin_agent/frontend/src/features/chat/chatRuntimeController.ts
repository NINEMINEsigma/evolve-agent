import { HISTORY_PAGE_OVERSCAN_ROWS, HISTORY_PAGE_SIZE } from "../../constants/history";
import { historyContentRowToChatMessage } from "./historyProjection";
import { fetchHistoryPage, fetchHistoryResources, fetchHistorySkeleton } from "./historyApi";
import { selectChatRenderRows, useChatRuntimeStore } from "./chatRuntimeStore";
import type { ClientDiagnostic } from "../../types";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";
import type { RegenerateTrimPayload } from "./types";

interface HistoryReloadRequest {
  sessionId: string;
  generation: number;
  promise: Promise<void>;
  pendingCount: number | null;
}

class ChatRuntimeController {
  private historyReload: HistoryReloadRequest | null = null;
  private controllers = new Set<AbortController>();
  private pageRequests = new Map<string, { promise: Promise<void> }>();
  private diagnosticReporter: ((diagnostic: ClientDiagnostic) => void) | null = null;

  setDiagnosticReporter(
    reporter: ((diagnostic: ClientDiagnostic) => void) | null,
  ): void {
    this.diagnosticReporter = reporter;
  }

  private reportTimeout(
    error: RequestTimeoutError,
    sessionId: string,
    generation: number,
  ): void {
    if (!this.isCurrent(sessionId, generation)) return;
    if (error.phase !== "history_skeleton" && error.phase !== "history_page") return;
    this.diagnosticReporter?.({
      kind: "critical_request_timeout",
      phase: error.phase,
      duration_ms: Math.max(0, Math.round(error.elapsedMs)),
      websocket_state: "unknown",
    });
  }

  beginSession(sessionId: string): void {
    this.abortAll();
    useChatRuntimeStore.getState().beginSession(sessionId);
  }

  resetSession(): void {
    this.abortAll();
    useChatRuntimeStore.getState().resetSession();
  }

  reloadHistory(sessionId: string, liveCutoffVersion?: number): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (!sessionId || state.sessionId !== sessionId) return Promise.resolve();
    this.abortAll();
    state.invalidateHistory(sessionId, liveCutoffVersion);
    return this.retryHistoryReload();
  }

  private retryHistoryReload(): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId) return Promise.resolve();
    if (this.historyReload?.sessionId === state.sessionId
      && this.historyReload.generation === state.generation) return this.historyReload.promise;
    const request: HistoryReloadRequest = {
      sessionId: state.sessionId,
      generation: state.generation,
      promise: Promise.resolve(),
      pendingCount: null,
    };
    this.historyReload = request;
    state.setSkeletonLoading(true);
    state.setSkeletonError(null);
    request.promise = this.readHistoryReload(request);
    return request.promise;
  }

  private async readHistoryReload(request: HistoryReloadRequest): Promise<void> {
    const { sessionId, generation } = request;
    try {
      const skeleton = await this.withController((signal) => fetchHistorySkeleton(sessionId, 0, signal));
      if (!this.isCurrent(sessionId, generation)) return;
      const start = Math.max(0, skeleton.history_count - HISTORY_PAGE_SIZE);
      const page = skeleton.history_count > 0
        ? await this.withController((signal) => fetchHistoryPage(
          sessionId, start, HISTORY_PAGE_SIZE, signal,
        ))
        : null;
      if (!this.isCurrent(sessionId, generation)) return;
      useChatRuntimeStore.getState().applyHistoryReload(
        skeleton.rows, skeleton.history_count,
        page?.rows.map(historyContentRowToChatMessage) ?? [],
        page?.start_index ?? 0, page?.end_index ?? 0, generation,
      );
      request.pendingCount = Math.max(
        request.pendingCount ?? 0, skeleton.history_count, page?.history_count ?? 0,
      );
      while (request.pendingCount !== null && this.isCurrent(sessionId, generation)) {
        const count = request.pendingCount;
        request.pendingCount = null;
        if (count > useChatRuntimeStore.getState().knownHistoryCount) {
          await this.syncHistory(sessionId, generation, count);
        }
      }
      if (this.isCurrent(sessionId, generation)) useChatRuntimeStore.getState().reconcileCanonicalTail();
    } catch (error) {
      if (this.isAbort(error) || !this.isCurrent(sessionId, generation)) return;
      if (error instanceof RequestTimeoutError) this.reportTimeout(error, sessionId, generation);
      useChatRuntimeStore.getState().setSkeletonError(this.errorMessage(error));
    } finally {
      if (this.historyReload === request) this.historyReload = null;
      if (this.isCurrent(sessionId, generation)) useChatRuntimeStore.getState().setSkeletonLoading(false);
    }
  }

  async initialize(sessionId: string, historyCount: number): Promise<void> {
    const store = useChatRuntimeStore.getState();
    if (store.sessionId === sessionId && (store.historyReloadRequired
      || this.historyReload?.generation === store.generation && this.historyReload.sessionId === sessionId)) {
      return this.retryHistoryReload();
    }
    if (store.sessionId !== sessionId) this.beginSession(sessionId);
    const generation = useChatRuntimeStore.getState().generation;
    store.setSkeletonLoading(true);
    store.setSkeletonError(null);
    try {
      const skeleton = await this.withController((signal) =>
        fetchHistorySkeleton(sessionId, 0, signal));
      if (!this.isCurrent(sessionId, generation)) return;
      useChatRuntimeStore.getState().replaceSkeleton(skeleton.rows, skeleton.history_count);
      if (historyCount > 0) {
        const start = Math.max(0, skeleton.history_count - HISTORY_PAGE_SIZE);
        await this.loadPage(sessionId, generation, start, HISTORY_PAGE_SIZE);
      }
      if (!this.isCurrent(sessionId, generation)) return;
      if (skeleton.rows.length === 0) {
        useChatRuntimeStore.getState().setInitialReady(true);
        useChatRuntimeStore.getState().setFollowMode("following");
      }
    } catch (error) {
      if (this.isAbort(error) || !this.isCurrent(sessionId, generation)) return;
      if (error instanceof RequestTimeoutError) this.reportTimeout(error, sessionId, generation);
      useChatRuntimeStore.getState().setSkeletonError(this.errorMessage(error));
    } finally {
      if (this.isCurrent(sessionId, generation)) {
        useChatRuntimeStore.getState().setSkeletonLoading(false);
      }
    }
  }

  async ensureVisibleRangeLoaded(startRow: number, endRow: number): Promise<void> {
    const reload = this.historyReload;
    if (reload) {
      await reload.promise;
      if (!this.isCurrent(reload.sessionId, reload.generation)) return;
    }
    const state = useChatRuntimeStore.getState();
    if (state.historyReloadRequired) return;
    if (!state.sessionId || state.skeleton.length === 0) return;
    // Virtuoso 传入的是过滤后的展示行索引，不能直接索引完整骨架。
    const rows = selectChatRenderRows(state);
    const start = Math.max(0, startRow - HISTORY_PAGE_OVERSCAN_ROWS);
    const end = Math.min(rows.length - 1, endRow + HISTORY_PAGE_OVERSCAN_ROWS);
    const pages = new Set<number>();
    for (let index = start; index <= end; index += 1) {
      const historyIndex = rows[index].historyIndex;
      if (historyIndex !== null) {
        pages.add(Math.floor(historyIndex / HISTORY_PAGE_SIZE) * HISTORY_PAGE_SIZE);
      }
    }
    for (const pageStart of pages) {
      const current = useChatRuntimeStore.getState();
      let missing = false;
      const pageEnd = Math.min(current.knownHistoryCount, pageStart + HISTORY_PAGE_SIZE);
      for (let index = pageStart; index < pageEnd; index += 1) {
        if (!current.loadedHistoryIndices.has(index)) {
          missing = true;
          break;
        }
      }
      if (missing) {
        void this.loadPage(current.sessionId, current.generation, pageStart, HISTORY_PAGE_SIZE);
      }
    }
  }

  async jumpToLogicalRow(rowIndex: number): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (state.historyReloadRequired || this.historyReload) return;
    const row = selectChatRenderRows(state)[rowIndex];
    if (!row || row.historyIndex === null) return;
    const start = Math.max(0, row.historyIndex - Math.floor(HISTORY_PAGE_SIZE / 2));
    await this.loadPage(state.sessionId, state.generation, start, HISTORY_PAGE_SIZE);
  }

  async syncCanonicalHistory(historyCount: number): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId) return;
    if (state.historyReloadRequired || this.historyReload?.sessionId === state.sessionId) {
      const promise = this.retryHistoryReload();
      if (this.historyReload) {
        this.historyReload.pendingCount = Math.max(this.historyReload.pendingCount ?? 0, historyCount);
      }
      return promise;
    }
    return this.syncHistory(state.sessionId, state.generation, historyCount);
  }

  private async syncHistory(sessionId: string, generation: number, historyCount: number): Promise<void> {
    if (!this.isCurrent(sessionId, generation)) return;
    const state = useChatRuntimeStore.getState();
    try {
      if (historyCount < state.knownHistoryCount) {
        const full = await this.withController((signal) =>
          fetchHistorySkeleton(sessionId, 0, signal));
        if (!this.isCurrent(sessionId, generation)) return;
        const store = useChatRuntimeStore.getState();
        if (full.history_count < store.knownHistoryCount) {
          store.replaceSkeleton(full.rows, full.history_count);
          store.clearLive();
        } else if (full.history_count > store.knownHistoryCount) {
          store.appendSkeleton(
            full.rows.filter((row) => row.history_index >= store.knownHistoryCount), full.history_count,
          );
        }
        // WS计数可能早于完整重载的REST快照，不能据迟到计数清掉新的实时行。
        historyCount = full.history_count;
      } else if (historyCount > state.knownHistoryCount) {
        const suffix = await this.withController((signal) =>
          fetchHistorySkeleton(sessionId, state.knownHistoryCount, signal));
        if (!this.isCurrent(sessionId, generation)) return;
        useChatRuntimeStore.getState().appendSkeleton(suffix.rows, suffix.history_count);
      }
      useChatRuntimeStore.getState().promoteMappedLiveRows();
      const current = useChatRuntimeStore.getState();
      if (historyCount > 0) {
        await this.loadPage(
          sessionId,
          generation,
          Math.max(0, historyCount - HISTORY_PAGE_SIZE),
          HISTORY_PAGE_SIZE,
        );
        const verified = useChatRuntimeStore.getState();
        const tailStart = Math.max(0, historyCount - HISTORY_PAGE_SIZE);
        for (let index = tailStart; index < historyCount; index += 1) {
          if (!verified.loadedHistoryIndices.has(index)) {
            throw new Error("正典历史尾页尚未包含最新消息");
          }
        }
      }
      if (!this.isCurrent(sessionId, generation)) return;
      useChatRuntimeStore.getState().reconcileCanonicalTail();
      if (!current.initialReady) useChatRuntimeStore.getState().setInitialReady(true);
    } catch (error) {
      if (this.isAbort(error) || !this.isCurrent(sessionId, generation)) return;
      if (error instanceof RequestTimeoutError) this.reportTimeout(error, sessionId, generation);
      useChatRuntimeStore.getState().setSkeletonError(
        `正典历史同步失败：${this.errorMessage(error)}`,
      );
    }
  }

  applyRegenerateTrim(sessionId: string, trim: RegenerateTrimPayload): boolean {
    const state = useChatRuntimeStore.getState();
    if (!sessionId || state.sessionId !== sessionId) return false;
    this.abortAll();
    state.trimHistoryForRegeneration(trim);
    const current = useChatRuntimeStore.getState();
    if (!current.skeleton.some((row) => row.history_index === trim.message_index
      && row.row_kind === "message" && row.role === "user")) {
      void this.initialize(sessionId, trim.keep_count);
    }
    return true;
  }

  async invalidateAfterMutation(historyCount?: number): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId) return;
    const sessionId = state.sessionId;
    const draftHtml = state.draftHtml;
    const draftText = state.draftText;
    this.abortAll();
    useChatRuntimeStore.getState().beginSession(sessionId);
    useChatRuntimeStore.getState().setDraft(draftHtml, draftText);
    await this.initialize(sessionId, historyCount ?? 0);
  }

  async loadResources(force = false): Promise<void> {
    const reload = this.historyReload;
    if (reload) {
      await reload.promise;
      if (!this.isCurrent(reload.sessionId, reload.generation)) return;
    }
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId || state.historyReloadRequired
      || state.resourcesLoading || (state.resources && !force)) return;
    const sessionId = state.sessionId;
    const generation = state.generation;
    state.setResourcesLoading(true);
    state.setResourcesError(null);
    try {
      const resources = await this.withController((signal) =>
        fetchHistoryResources(sessionId, signal));
      if (!this.isCurrent(sessionId, generation)) return;
      useChatRuntimeStore.getState().setResources(resources);
    } catch (error) {
      if (!this.isAbort(error) && this.isCurrent(sessionId, generation)) {
        useChatRuntimeStore.getState().setResourcesError(this.errorMessage(error));
      }
    } finally {
      if (this.isCurrent(sessionId, generation)) {
        useChatRuntimeStore.getState().setResourcesLoading(false);
      }
    }
  }

  retryPage(startIndex: number, endIndex: number): void {
    const state = useChatRuntimeStore.getState();
    const reload = this.historyReload;
    if (reload) {
      void reload.promise.then(() => {
        if (this.isCurrent(reload.sessionId, reload.generation)) this.retryPage(startIndex, endIndex);
      });
      return;
    }
    if (state.historyReloadRequired) return;
    void this.loadPage(
      state.sessionId,
      state.generation,
      startIndex,
      Math.max(1, endIndex - startIndex),
    );
  }

  abortAll(): void {
    this.historyReload = null;
    for (const controller of this.controllers) controller.abort();
    this.controllers.clear();
    this.pageRequests.clear();
  }

  private loadPage(
    sessionId: string,
    generation: number,
    startIndex: number,
    limit: number,
  ): Promise<void> {
    const key = `${sessionId}:${generation}:${startIndex}:${limit}`;
    const existing = this.pageRequests.get(key);
    if (existing) return existing.promise;
    const request: { promise: Promise<void> } = {
      promise: Promise.resolve(),
    };
    request.promise = this.withController((signal) =>
      fetchHistoryPage(sessionId, startIndex, limit, signal))
      .then((page) => {
        if (!this.isCurrent(sessionId, generation)) return;
        useChatRuntimeStore.getState().mergeHistoryPage(
          page.rows.map(historyContentRowToChatMessage),
          page.start_index,
          page.end_index,
          this.historyReload?.generation === generation,
        );
      })
      .catch((error) => {
        if (this.isAbort(error) || !this.isCurrent(sessionId, generation)) return;
        if (error instanceof RequestTimeoutError) this.reportTimeout(error, sessionId, generation);
        useChatRuntimeStore.getState().setPageError({
          key: `${startIndex}:${startIndex + limit}`,
          startIndex,
          endIndex: startIndex + limit,
          message: this.errorMessage(error),
          retryable: true,
        });
      })
      .finally(() => {
        if (this.pageRequests.get(key) === request) this.pageRequests.delete(key);
      });
    this.pageRequests.set(key, request);
    return request.promise;
  }

  private async withController<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const controller = new AbortController();
    this.controllers.add(controller);
    try {
      return await operation(controller.signal);
    } finally {
      this.controllers.delete(controller);
    }
  }

  private isCurrent(sessionId: string, generation: number): boolean {
    const state = useChatRuntimeStore.getState();
    return state.sessionId === sessionId && state.generation === generation;
  }

  private isAbort(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
  }

  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : "未知错误";
  }
}

export const chatRuntimeController = new ChatRuntimeController();
