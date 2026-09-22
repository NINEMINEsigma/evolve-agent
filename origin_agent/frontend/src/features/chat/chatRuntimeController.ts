import { HISTORY_PAGE_OVERSCAN_ROWS, HISTORY_PAGE_SIZE } from "../../constants/history";
import { historyContentRowToChatMessage, historyIndexRangeForRows } from "./historyProjection";
import { fetchHistoryPage, fetchHistoryResources, fetchHistorySkeleton } from "./historyApi";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import type { ClientDiagnostic } from "../../types";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";

class ChatRuntimeController {
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

  async initialize(sessionId: string, historyCount: number): Promise<void> {
    const store = useChatRuntimeStore.getState();
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
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId || state.skeleton.length === 0 || state.followMode === "minimap_dragging") return;
    const start = Math.max(0, startRow - HISTORY_PAGE_OVERSCAN_ROWS);
    const end = Math.min(state.skeleton.length - 1, endRow + HISTORY_PAGE_OVERSCAN_ROWS);
    const range = historyIndexRangeForRows(state.skeleton, start, end);
    if (!range) return;
    const firstPage = Math.floor(range.startIndex / HISTORY_PAGE_SIZE) * HISTORY_PAGE_SIZE;
    const finalIndex = range.startIndex + range.limit;
    for (let pageStart = firstPage; pageStart < finalIndex; pageStart += HISTORY_PAGE_SIZE) {
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
    const row = state.skeleton[rowIndex];
    if (!row) return;
    const start = Math.max(0, row.history_index - Math.floor(HISTORY_PAGE_SIZE / 2));
    await this.loadPage(state.sessionId, state.generation, start, HISTORY_PAGE_SIZE);
  }

  async syncCanonicalHistory(historyCount: number): Promise<void> {
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId) return;
    const sessionId = state.sessionId;
    const generation = state.generation;
    try {
      if (historyCount < state.knownHistoryCount) {
        const full = await this.withController((signal) =>
          fetchHistorySkeleton(sessionId, 0, signal));
        if (!this.isCurrent(sessionId, generation)) return;
        useChatRuntimeStore.getState().replaceSkeleton(full.rows, full.history_count);
        useChatRuntimeStore.getState().clearLive();
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
      useChatRuntimeStore.getState().setProcessing(false);
      if (!current.initialReady) useChatRuntimeStore.getState().setInitialReady(true);
    } catch (error) {
      if (this.isAbort(error) || !this.isCurrent(sessionId, generation)) return;
      if (error instanceof RequestTimeoutError) this.reportTimeout(error, sessionId, generation);
      useChatRuntimeStore.getState().setSkeletonError(
        `正典历史同步失败：${this.errorMessage(error)}`,
      );
    }
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
    const state = useChatRuntimeStore.getState();
    if (!state.sessionId || state.resourcesLoading || (state.resources && !force)) return;
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
    void this.loadPage(
      state.sessionId,
      state.generation,
      startIndex,
      Math.max(1, endIndex - startIndex),
    );
  }

  abortAll(): void {
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
