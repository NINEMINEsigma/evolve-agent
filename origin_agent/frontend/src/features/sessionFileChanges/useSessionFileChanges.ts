import { useCallback, useEffect, useRef, useState } from "react";
import { SESSION_FILE_CHANGES_PAGE_LIMIT } from "../../constants/sessionFileChanges";
import { TIMING } from "../../constants/timing";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";
import {
  fetchSessionFileChangesPage, fetchSessionFileChangesSummary,
  SessionFileChangesProtocolError, SessionFileChangesRequestError,
} from "./api";
import { fileChangesLabels, formatFileChangesLabel } from "./labels";
import type {
  SessionFileChangesPageDto, SessionFileChangeEntryDto, SessionFileChangesStatus, SessionFileChangesSummaryDto,
  UseSessionFileChangesState,
} from "./types";

function describeFailure(failure: unknown, fallback: string): string {
  if (failure instanceof RequestTimeoutError) return fileChangesLabels.requestTimeout;
  if (failure instanceof SessionFileChangesProtocolError) {
    return formatFileChangesLabel(fileChangesLabels.protocolError, { detail: failure.message });
  }
  if (failure instanceof SessionFileChangesRequestError) {
    return formatFileChangesLabel(fileChangesLabels.requestFailed, { status: failure.status });
  }
  return fallback;
}

/** Aborting a read must not leave "loading"/"refreshing" behind; keep error/ready. */
function settleStatus(
  previous: SessionFileChangesStatus, hasSnapshot: boolean,
): SessionFileChangesStatus {
  if (previous !== "loading" && previous !== "refreshing") return previous;
  return hasSnapshot ? "ready" : "idle";
}

/**
 * Single source for session file changes: one serial summary poll plus one page
 * chain for the active tab. Session id and request epochs reject late responses;
 * queued work is collapsed to at most one pending refresh per chain.
 */
export function useSessionFileChanges(
  sessionId: string, active: boolean, enabled: boolean,
): UseSessionFileChangesState {
  const [summary, setSummary] = useState<SessionFileChangesSummaryDto | null>(null);
  const [summaryStatus, setSummaryStatus] = useState<SessionFileChangesStatus>("idle");
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [page, setPage] = useState<SessionFileChangesPageDto | null>(null);
  const [pageStatus, setPageStatus] = useState<SessionFileChangesStatus>("idle");
  const [pageError, setPageError] = useState<string | null>(null);
  const [treeEntries, setTreeEntries] = useState<readonly SessionFileChangeEntryDto[] | null>(null);
  const [treeStatus, setTreeStatus] = useState<SessionFileChangesStatus>("idle");
  const [treeError, setTreeError] = useState<string | null>(null);
  const [offset, setOffsetState] = useState(0);

  const scopeRef = useRef<string>(sessionId);
  const generationRef = useRef(0);
  const summaryEpochRef = useRef(0);
  const pageEpochRef = useRef(0);
  const summaryControllerRef = useRef<AbortController | null>(null);
  const pageControllerRef = useRef<AbortController | null>(null);
  const treeControllerRef = useRef<AbortController | null>(null);
  const treeEpochRef = useRef(0);
  const treeInFlightRef = useRef(false);
  const treeRevisionRef = useRef<number | null>(null);
  const summaryTimerRef = useRef<number | null>(null);
  const summaryInFlightRef = useRef(false);
  const summaryQueuedRef = useRef(false);
  const pageInFlightRef = useRef<number | null>(null);
  const pageQueuedRef = useRef(false);

  const sessionRef = useRef(sessionId);
  const activeRef = useRef(active);
  const enabledRef = useRef(enabled);
  const offsetRef = useRef(offset);
  const summaryRef = useRef<SessionFileChangesSummaryDto | null>(summary);
  const pageRef = useRef<SessionFileChangesPageDto | null>(page);
  const treeEntriesRef = useRef<readonly SessionFileChangeEntryDto[] | null>(treeEntries);
  sessionRef.current = sessionId;
  activeRef.current = active;
  enabledRef.current = enabled;
  offsetRef.current = offset;
  treeEntriesRef.current = treeEntries;

  const clearSummaryTimer = useCallback(() => {
    if (summaryTimerRef.current !== null) {
      window.clearTimeout(summaryTimerRef.current);
      summaryTimerRef.current = null;
    }
  }, []);

  const abortSummary = useCallback(() => {
    ++summaryEpochRef.current;
    summaryControllerRef.current?.abort();
    summaryControllerRef.current = null;
    summaryInFlightRef.current = false;
    summaryQueuedRef.current = false;
    clearSummaryTimer();
  }, [clearSummaryTimer]);

  const abortPage = useCallback(() => {
    ++pageEpochRef.current;
    pageControllerRef.current?.abort();
    pageControllerRef.current = null;
    pageInFlightRef.current = null;
    pageQueuedRef.current = false;
  }, []);

  const abortTree = useCallback(() => {
    ++treeEpochRef.current;
    treeControllerRef.current?.abort();
    treeControllerRef.current = null;
    treeInFlightRef.current = false;
  }, []);

  const clearAll = useCallback(() => {
    summaryRef.current = null;
    pageRef.current = null;
    treeEntriesRef.current = null;
    treeRevisionRef.current = null;
    offsetRef.current = 0;
    setSummary(null);
    setPage(null);
    setTreeEntries(null);
    setTreeError(null);
    setTreeStatus("idle");
    setSummaryError(null);
    setPageError(null);
    setSummaryStatus("idle");
    setPageStatus("idle");
    setOffsetState(0);
  }, []);

  /**
   * A 404 means the session is gone (or deleting): invalidate both chains and
   * drop every value of this scope. The generation bump also prevents a
   * concurrent response from resurrecting data after the clear.
   */
  const handleGone = useCallback(() => {
    ++generationRef.current;
    abortSummary();
    abortPage();
    abortTree();
    clearAll();
  }, [abortPage, abortSummary, abortTree, clearAll]);

  /** Monotonic commit: an older summary never replaces the current snapshot. */
  const commitSummary = useCallback((next: SessionFileChangesSummaryDto): boolean => {
    const current = summaryRef.current;
    if (current !== null && next.revision < current.revision) return false;
    summaryRef.current = next;
    setSummary(next);
    setSummaryStatus("ready");
    setSummaryError(null);
    return true;
  }, []);

  const runSummaryRef = useRef<() => Promise<void>>(async () => {});
  const runTreeRef = useRef<() => Promise<void>>(async () => {});
  const runPageRef = useRef<(targetOffset: number) => Promise<void>>(async () => {});

  const scheduleSummaryPoll = useCallback(() => {
    if (!enabledRef.current || document.hidden || summaryTimerRef.current !== null) return;
    summaryTimerRef.current = window.setTimeout(() => {
      summaryTimerRef.current = null;
      if (!enabledRef.current || document.hidden) return;
      void runSummaryRef.current();
    }, TIMING.SESSION_FILE_CHANGES_POLL_INTERVAL);
  }, []);

  const runSummary = useCallback(async (): Promise<void> => {
    const sid = sessionRef.current;
    if (!enabledRef.current || !sid || document.hidden) return;
    if (summaryInFlightRef.current) {
      summaryQueuedRef.current = true;
      return;
    }
    clearSummaryTimer();
    const owner = generationRef.current;
    const epoch = ++summaryEpochRef.current;
    const controller = new AbortController();
    summaryControllerRef.current = controller;
    summaryInFlightRef.current = true;
    setSummaryStatus(summaryRef.current === null ? "loading" : "refreshing");
    try {
      const result = await fetchSessionFileChangesSummary(sid, controller.signal);
      if (generationRef.current !== owner || summaryEpochRef.current !== epoch
        || sessionRef.current !== sid || !enabledRef.current || controller.signal.aborted) return;
      // A newer page snapshot may have committed first; the held summary is
      // already authoritative, so this read only settles the status.
      if (!commitSummary(result)) setSummaryStatus("ready");
    } catch (failure) {
      if (generationRef.current !== owner || summaryEpochRef.current !== epoch
        || sessionRef.current !== sid || !enabledRef.current || controller.signal.aborted) return;
      if (failure instanceof SessionFileChangesRequestError && failure.status === 404) {
        handleGone();
        scheduleSummaryPoll();
        return;
      }
      setSummaryStatus("error");
      setSummaryError(describeFailure(failure, fileChangesLabels.summaryReadFailed));
    } finally {
      if (summaryEpochRef.current === epoch) {
        summaryInFlightRef.current = false;
        summaryControllerRef.current = null;
        if (generationRef.current === owner && sessionRef.current === sid) {
          if (summaryQueuedRef.current && enabledRef.current && !document.hidden) {
            summaryQueuedRef.current = false;
            void runSummaryRef.current();
          } else {
            summaryQueuedRef.current = false;
            scheduleSummaryPoll();
          }
        }
      }
    }
  }, [clearSummaryTimer, commitSummary, handleGone, scheduleSummaryPoll]);
  runSummaryRef.current = runSummary;

  const runTree = useCallback(async (): Promise<void> => {
    const sid = sessionRef.current;
    if (!enabledRef.current || !activeRef.current || !sid || document.hidden) return;
    if (treeInFlightRef.current) return;
    const owner = generationRef.current;
    const epoch = ++treeEpochRef.current;
    const controller = new AbortController();
    treeControllerRef.current = controller;
    treeInFlightRef.current = true;
    const existing = treeEntriesRef.current;
    setTreeStatus(existing === null ? "loading" : "refreshing");
    setTreeError(null);
    const items: SessionFileChangeEntryDto[] = [];
    let offset = 0;
    let expectedRevision: number | null = null;
    try {
      while (true) {
        const result = await fetchSessionFileChangesPage(
          sid, offset, SESSION_FILE_CHANGES_PAGE_LIMIT, controller.signal,
        );
        if (expectedRevision === null) expectedRevision = result.summary.revision;
        if (result.summary.revision !== expectedRevision) {
          throw new SessionFileChangesProtocolError("File changes tree spans multiple revisions");
        }
        items.push(...result.items);
        if (items.length >= result.total_count) break;
        if (result.items.length === 0) {
          throw new SessionFileChangesProtocolError("File changes tree page ended before the declared total");
        }
        offset += result.items.length;
      }
      if (generationRef.current !== owner || treeEpochRef.current !== epoch
        || sessionRef.current !== sid || !activeRef.current || !enabledRef.current
        || controller.signal.aborted) return;
      treeEntriesRef.current = items;
      treeRevisionRef.current = expectedRevision;
      setTreeEntries(items);
      setTreeStatus("ready");
      setTreeError(null);
    } catch (failure) {
      if (generationRef.current !== owner || treeEpochRef.current !== epoch
        || sessionRef.current !== sid || controller.signal.aborted) return;
      if (failure instanceof SessionFileChangesRequestError && failure.status === 404) {
        handleGone();
        scheduleSummaryPoll();
        return;
      }
      setTreeStatus("error");
      setTreeError(describeFailure(failure, fileChangesLabels.pageReadFailed));
    } finally {
      if (treeEpochRef.current === epoch) {
        treeInFlightRef.current = false;
        treeControllerRef.current = null;
        if (generationRef.current === owner && sessionRef.current === sid
          && activeRef.current && enabledRef.current && !document.hidden
          && expectedRevision !== null && summaryRef.current?.revision !== expectedRevision) {
          void runTreeRef.current();
        }
      }
    }
  }, [handleGone, scheduleSummaryPoll]);
  runTreeRef.current = runTree;

  const runPage = useCallback(async (targetOffset: number): Promise<void> => {
    const sid = sessionRef.current;
    if (!enabledRef.current || !activeRef.current || !sid || document.hidden) return;
    if (offsetRef.current !== targetOffset) return;
    if (pageInFlightRef.current !== null) {
      if (pageInFlightRef.current === targetOffset) {
        pageQueuedRef.current = true;
        return;
      }
      abortPage();
    }
    const owner = generationRef.current;
    const epoch = ++pageEpochRef.current;
    const controller = new AbortController();
    pageControllerRef.current = controller;
    pageInFlightRef.current = targetOffset;
    const existing = pageRef.current;
    const samePage = existing !== null && existing.summary.session_id === sid
      && existing.offset === targetOffset;
    setPageStatus(samePage ? "refreshing" : "loading");
    setPageError(null);
    try {
      const result = await fetchSessionFileChangesPage(
        sid, targetOffset, SESSION_FILE_CHANGES_PAGE_LIMIT, controller.signal,
      );
      if (generationRef.current !== owner || pageEpochRef.current !== epoch
        || sessionRef.current !== sid || offsetRef.current !== targetOffset
        || !activeRef.current || !enabledRef.current || controller.signal.aborted) return;
      const previous = pageRef.current;
      if (previous !== null && previous.summary.session_id === sid
        && previous.offset === result.offset
        && previous.summary.revision > result.summary.revision) {
        // A newer snapshot for the same offset already exists; never overwrite it.
        pageQueuedRef.current = true;
        return;
      }
      const summaryAccepted = commitSummary(result.summary);
      pageRef.current = result;
      setPage(result);
      setPageStatus("ready");
      setPageError(null);
      if (!summaryAccepted && summaryRef.current !== null
        && result.summary.revision < summaryRef.current.revision) {
        pageQueuedRef.current = true;
      }
    } catch (failure) {
      if (generationRef.current !== owner || pageEpochRef.current !== epoch
        || sessionRef.current !== sid || offsetRef.current !== targetOffset
        || !activeRef.current || !enabledRef.current || controller.signal.aborted) return;
      if (failure instanceof SessionFileChangesRequestError && failure.status === 404) {
        handleGone();
        scheduleSummaryPoll();
        return;
      }
      // Keep the same-session snapshot visible; the page is explicitly stale.
      setPageStatus("error");
      setPageError(describeFailure(failure, fileChangesLabels.pageReadFailed));
    } finally {
      if (pageEpochRef.current === epoch) {
        pageInFlightRef.current = null;
        pageControllerRef.current = null;
        if (generationRef.current === owner && sessionRef.current === sid
          && enabledRef.current && activeRef.current) {
          if (pageQueuedRef.current) {
            pageQueuedRef.current = false;
            void runPageRef.current(offsetRef.current);
          }
        } else {
          pageQueuedRef.current = false;
        }
      }
    }
  }, [abortPage, commitSummary, handleGone, scheduleSummaryPoll]);
  runPageRef.current = runPage;

  const setOffset = useCallback((next: number) => {
    if (!Number.isSafeInteger(next) || next < 0) {
      throw new Error("Invalid file changes page offset");
    }
    if (next === offsetRef.current) return;
    offsetRef.current = next;
    setOffsetState(next);
    if (!activeRef.current) return;
    abortPage();
    void runPageRef.current(next);
  }, [abortPage]);

  const refresh = useCallback(async (): Promise<void> => {
    if (!enabledRef.current || !sessionRef.current) return;
    const owner = generationRef.current;
    await runSummaryRef.current();
    // A 404 during the summary read invalidated this scope; do not start a page.
    if (generationRef.current !== owner) return;
    if (enabledRef.current && activeRef.current) {
      void runTreeRef.current();
    }
  }, []);

  // Session scope and enablement: abort both chains, reset data on a session
  // switch, then read the summary immediately when requests are allowed.
  useEffect(() => {
    ++generationRef.current;
    abortSummary();
    abortPage();
    abortTree();
    const scopeChanged = scopeRef.current !== sessionId;
    if (scopeChanged) {
      scopeRef.current = sessionId;
      clearAll();
    }
    if (!enabled) {
      // Preserve an existing error/snapshot state; only settle interrupted reads.
      setSummaryStatus((previous) => settleStatus(previous, summaryRef.current !== null));
      setPageStatus((previous) => settleStatus(previous, pageRef.current !== null));
      setTreeStatus((previous) => settleStatus(previous, treeEntriesRef.current !== null));
    }
    if (enabled && sessionId && !document.hidden) void runSummaryRef.current();
    return () => {
      ++generationRef.current;
      abortSummary();
      abortPage();
      abortTree();
    };
  }, [abortPage, abortSummary, abortTree, clearAll, enabled, sessionId]);

  // Every activation gets one complete tree, even when the summary revision is unchanged.
  useEffect(() => {
    if (active && enabled) void runTreeRef.current();
  }, [active, enabled, sessionId]);

  // A newer summary revision invalidates the current tree and reloads all visible pages.
  useEffect(() => {
    if (active && enabled && summary?.revision !== undefined) void runTreeRef.current();
  }, [active, enabled, sessionId, summary?.revision]);

  // Leaving the tab cancels the page chain but keeps the snapshot for preview.
  useEffect(() => {
    if (active) return;
    abortPage();
    abortTree();
    setPageStatus((previous) => settleStatus(previous, pageRef.current !== null));
    setTreeStatus((previous) => settleStatus(previous, treeEntriesRef.current !== null));
  }, [abortPage, abortTree, active]);

  // Hidden pages pause automatic polling and cancel in-flight reads; the same
  // snapshots stay available and a fresh read starts when the page is visible.
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.hidden) {
        abortSummary();
        abortPage();
        abortTree();
        setSummaryStatus((previous) => settleStatus(previous, summaryRef.current !== null));
        setPageStatus((previous) => settleStatus(previous, pageRef.current !== null));
        setTreeStatus((previous) => settleStatus(previous, treeEntriesRef.current !== null));
        return;
      }
      if (!enabledRef.current || !sessionRef.current) return;
      void runSummaryRef.current();
      if (activeRef.current) void runTreeRef.current();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [abortPage, abortSummary, abortTree]);

  const currentSummary = summary !== null && summary.session_id === sessionId ? summary : null;
  const currentPage = page !== null && page.summary.session_id === sessionId ? page : null;
  const currentTree = scopeRef.current === sessionId ? treeEntries : null;
  const scoped = scopeRef.current === sessionId || currentSummary !== null || currentPage !== null;
  const pageStale = currentPage !== null
    && (pageError !== null || (currentSummary !== null && currentPage.summary.revision !== currentSummary.revision));
  const treeStale = currentTree !== null
    && (treeError !== null || (currentSummary !== null && treeRevisionRef.current !== currentSummary.revision));

  return {
    summary: currentSummary,
    summaryStatus: scoped ? summaryStatus : "idle",
    summaryError: scoped ? summaryError : null,
    page: currentPage,
    pageStatus: scoped ? pageStatus : "idle",
    pageError: scoped ? pageError : null,
    pageStale,
    treeEntries: currentTree,
    treeStatus: scoped ? treeStatus : "idle",
    treeError: scoped ? treeError : null,
    treeStale,
    offset: scoped ? offset : 0,
    setOffset,
    refresh,
  };
}
