import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import { useSessionResourceSnapshot } from "./useSessionResourceSnapshot";
import type {
  SessionResourceScope,
  SessionResourceSnapshots,
  SessionResourceState,
} from "../types/sessionResources";
import type {
  ApprovalMode,
  ApprovalModeSyncStatus,
  AskAnswerItem,
  AskRequest,
  ConfirmRequest,
  CronTask,
  DynamicEndpoint,
  InterruptStatus,
  OperationNotice,
  SessionInfo,
  ShellInfo,
  SidebarItem,
  TaskProgress,
  WSMessage,
} from "../types";
import { STORAGE_KEYS } from "../constants/storage";
import { SID_SHORT_LEN } from "../constants/session";
import { WS_IN } from "../constants/ws";
import { TIMING } from "../constants/timing";
import { fetchJsonWithTimeout } from "../services/fetchJsonWithTimeout";
import { HttpResponseError, isPreExecutionRejection } from "../services/httpErrors";
import errorLabels from "../services/httpErrorLabels.json";

type InteractionKind = "confirm" | "ask";
type InteractionSubmissionPhase = "submitting" | "uncertain";
interface InteractionSubmission {
  kind: InteractionKind;
  requestId: string;
  scope: SessionResourceScope;
  payload: string;
  phase: InteractionSubmissionPhase;
  detached: boolean;
}

function responseRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(errorLabels.invalidResponse);
  return value as Record<string, unknown>;
}
function stringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
function requestSessionJson(
  path: string,
  init: RequestInit = {},
  timeoutMs: number | null = TIMING.CRITICAL_REQUEST_TIMEOUT,
): Promise<Record<string, unknown>> {
  return fetchJsonWithTimeout(path, init,
    { timeoutMs, phase: "session-operation" }, responseRecord);
}

interface SessionTerminationResponse {
  terminated: boolean;
  session_id: string;
  error?: string | null;
  metadata_warnings: string[];
}

function decodeSessionTerminationResult(value: unknown, expectedSessionId: string): SessionTerminationResponse {
  const data = responseRecord(value);
  const { terminated, session_id, error, metadata_warnings } = data;
  if (typeof terminated !== "boolean" || typeof session_id !== "string" || session_id !== expectedSessionId
    || !stringList(metadata_warnings)
    || (error !== undefined && error !== null && typeof error !== "string")) {
    throw new Error(errorLabels.invalidResponse);
  }
  const result: SessionTerminationResponse = { terminated, session_id, metadata_warnings };
  if (error !== undefined) result.error = error;
  return result;
}

interface SessionRefreshOptions {
  noticeScope?: SessionResourceScope;
  failureMessage?: string;
}

export interface SessionStoreCallbacks {
  onSessionRotated?: (newSid: string, oldSid: string) => void;
}

export interface SessionStore {
  pendingConfirms: ConfirmRequest[];
  pendingAsks: AskRequest[];
  clearPendingInteractions: () => void;
  sessionId: string;
  setSessionId: React.Dispatch<React.SetStateAction<string>>;
  tokenUsage: number;
  setTokenUsage: React.Dispatch<React.SetStateAction<number>>;
  contextTokens: number;
  setContextTokens: React.Dispatch<React.SetStateAction<number>>;
  sessions: SessionInfo[];
  setSessions: React.Dispatch<React.SetStateAction<SessionInfo[]>>;
  searchQuery: string;
  setSearchQuery: React.Dispatch<React.SetStateAction<string>>;
  approvalMode: ApprovalMode;
  setApprovalMode: React.Dispatch<React.SetStateAction<ApprovalMode>>;
  approvalModeSyncStatus: ApprovalModeSyncStatus;
  setApprovalModeSyncStatus: React.Dispatch<React.SetStateAction<ApprovalModeSyncStatus>>;
  taskProgress: Record<string, TaskProgress>;
  setTaskProgress: React.Dispatch<React.SetStateAction<Record<string, TaskProgress>>>;
  dynamicEndpoints: DynamicEndpoint[];
  setDynamicEndpoints: React.Dispatch<React.SetStateAction<DynamicEndpoint[]>>;
  shellResource: SessionResourceState<ShellInfo[]>;
  cronResource: SessionResourceState<CronTask[]>;
  dynamicEndpointResource: SessionResourceState<DynamicEndpoint[]>;
  resourceSnapshots: SessionResourceSnapshots;
  resourceScope: SessionResourceScope;
  isResourceScopeCurrent: (scope: SessionResourceScope) => boolean;
  agents: string[];
  setAgents: React.Dispatch<React.SetStateAction<string[]>>;
  mergeMode: boolean;
  setMergeMode: React.Dispatch<React.SetStateAction<boolean>>;
  selectedForMerge: Set<string>;
  setSelectedForMerge: React.Dispatch<React.SetStateAction<Set<string>>>;
  shells: ShellInfo[];
  setShells: React.Dispatch<React.SetStateAction<ShellInfo[]>>;
  cronTasks: CronTask[];
  setCronTasks: React.Dispatch<React.SetStateAction<CronTask[]>>;
  terminatingSessions: Set<string>;
  generatingTitleSessions: Set<string>;
  generatingTagSessions: Set<string>;
  generatingSummarySessions: Set<string>;
  operationNotice: OperationNotice | null;
  showOperationNotice: (notice: OperationNotice) => void;
  dismissOperationNotice: () => void;
  interruptStatus: InterruptStatus;
  setInterruptStatus: React.Dispatch<React.SetStateAction<InterruptStatus>>;
  allTags: string[];
  ignoreStaleRef: React.MutableRefObject<boolean>;
  fetchSessions: () => void;
  fetchAllTags: () => void;
  handleMessage: (message: WSMessage) => void;
  respondConfirm: (request: ConfirmRequest | null, action: string, reason?: string, deniedBy?: string) => void;
  respondAsk: (request: AskRequest | null, answers?: AskAnswerItem[] | null) => void;
  newChat: () => void;
  switchSession: (sid: string) => void;
  autoTitleSession: (sid: string) => void;
  autoTagSession: (sid: string) => void;
  regenerateSummary: (sid: string) => void;
  terminateSession: (sid: string) => void;
  togglePinSession: (sid: string) => void;
  renamingSessionId: string | null;
  setRenamingSessionId: React.Dispatch<React.SetStateAction<string | null>>;
  renameSession: (sid: string, title: string) => void;
  mergeSessions: (sources: string[]) => Promise<string | undefined>;
  toggleMergeSelect: (sid: string) => void;
  updateSessionTags: (sid: string, tags: string[]) => Promise<string[]>;
  sidebarItems: SidebarItem[];
  expandedClusters: Set<string>;
  toggleCluster: (id: string) => void;
}

export function useSessionStore(callbacks: SessionStoreCallbacks = {}): SessionStore {
  const [pendingConfirms, setPendingConfirms] = useState<ConfirmRequest[]>([]);
  const [pendingAsks, setPendingAsks] = useState<AskRequest[]>([]);
  const [sessionId, setSessionIdState] = useState("");
  const [tokenUsage, setTokenUsage] = useState(0);
  const [contextTokens, setContextTokens] = useState(0);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>("manual");
  const [approvalModeSyncStatus, setApprovalModeSyncStatus] = useState<ApprovalModeSyncStatus>("loading");
  const [taskProgress, setTaskProgress] = useState<Record<string, TaskProgress>>({});
  const [agents, setAgents] = useState<string[]>([]);
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set());
  const [terminatingSessions, setTerminatingSessions] = useState<Set<string>>(new Set());
  const [generatingTitleSessions, setGeneratingTitleSessions] = useState<Set<string>>(new Set());
  const [generatingTagSessions, setGeneratingTagSessions] = useState<Set<string>>(new Set());
  const [generatingSummarySessions, setGeneratingSummarySessions] = useState<Set<string>>(new Set());
  const [operationNotice, setOperationNotice] = useState<OperationNotice | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [interruptStatus, setInterruptStatus] = useState<InterruptStatus>("idle");
  const [allTags, setAllTags] = useState<string[]>([]);
  const [, setServerInfo] = useState<Record<string, unknown>>({});
  const [expandedClusters, setExpandedClusters] = usePersistentState<Set<string>>(
    STORAGE_KEYS.EXPANDED_CLUSTERS,
    new Set(),
    {
      serialize: (value) => JSON.stringify(Array.from(value)),
      deserialize: (value) => new Set(JSON.parse(value)),
    },
  );

  const interactionSubmissionsRef = useRef(new Map<string, InteractionSubmission>());
  const terminationRequestsRef = useRef(new Map<string, AbortController>());
  const sessionsRequestGenerationRef = useRef(0);
  const tagsRequestGenerationRef = useRef(0);
  const pendingAsksRef = useRef<AskRequest[]>([]);
  const pendingConfirmsRef = useRef<ConfirmRequest[]>([]);
  const callbacksRef = useRef(callbacks);
  const ignoreStaleRef = useRef(false);
  // 会话资源归属：sid 与单调代际；effect 同步 ref，用 sidRef 在 render 期判定真实变化。
  const resourceScopeRef = useRef<SessionResourceScope>({ sessionId: "", generation: 0 });
  const sidRef = useRef("");
  const shellResource = useSessionResourceSnapshot<ShellInfo[]>(resourceScopeRef);
  const cronResource = useSessionResourceSnapshot<CronTask[]>(resourceScopeRef);
  const dynamicEndpointResource = useSessionResourceSnapshot<DynamicEndpoint[]>(resourceScopeRef);

  useEffect(() => () => {
    sessionsRequestGenerationRef.current += 1;
    tagsRequestGenerationRef.current += 1;
    const controllers = [...terminationRequestsRef.current.values()];
    terminationRequestsRef.current.clear();
    for (const controller of controllers) controller.abort();
  }, []);

  const isResourceScopeCurrent = useCallback(
    (scope: SessionResourceScope): boolean => {
      const current = resourceScopeRef.current;
      return current.sessionId === scope.sessionId && current.generation === scope.generation;
    },
    [],
  );

  // 唯一 sessionId 写入口：真实变化时先同步 scope、重置三源，再提交 React state。
  const setSessionId = useCallback<React.Dispatch<React.SetStateAction<string>>>(
    (update) => {
      const previous = sidRef.current;
      const next = typeof update === "function" ? (update as (prev: string) => string)(previous) : update;
      if (next === previous) {
        setSessionIdState(next);
        return;
      }
      sidRef.current = next;
      resourceScopeRef.current = { sessionId: next, generation: resourceScopeRef.current.generation + 1 };
      shellResource.reset();
      cronResource.reset();
      dynamicEndpointResource.reset();
      setSessionIdState(next);
    },
    [shellResource.reset, cronResource.reset, dynamicEndpointResource.reset],
  );
  useEffect(() => { callbacksRef.current = callbacks; }, [callbacks]);
  useEffect(() => { sidRef.current = sessionId; }, [sessionId]);

  const submitInteraction = useCallback(async (
    kind: InteractionKind, requestId: string, payload: string,
    scope: SessionResourceScope, detached: boolean,
  ): Promise<void> => {
    const key = `${kind}:${requestId}`;
    const previous = interactionSubmissionsRef.current.get(key);
    if (previous?.phase === "submitting") {
      if (detached) previous.detached = true;
      return;
    }
    if (previous && previous.payload !== payload) {
      if (!detached && isResourceScopeCurrent(scope)) {
        setOperationNotice({ kind: "warning", message: errorLabels.interactionPayloadLocked });
      }
      return;
    }
    // 登记在首次 await 之前完成；同 ID 的在途请求只能有一个。
    const submission: InteractionSubmission = previous ?? {
      kind, requestId, payload, scope: { ...scope }, phase: "submitting", detached,
    };
    submission.phase = "submitting";
    submission.detached ||= detached;
    interactionSubmissionsRef.current.set(key, submission);
    const owns = () => interactionSubmissionsRef.current.get(key) === submission;
    const visible = () => owns() && !submission.detached && isResourceScopeCurrent(submission.scope);
    const consume = () => {
      if (kind === "confirm") {
        pendingConfirmsRef.current = pendingConfirmsRef.current.filter((item) => item.request_id !== requestId);
        setPendingConfirms(pendingConfirmsRef.current);
      } else {
        pendingAsksRef.current = pendingAsksRef.current.filter((item) => item.request_id !== requestId);
        setPendingAsks(pendingAsksRef.current);
      }
    };
    try {
      const data = await requestSessionJson(`/api/${kind}/${encodeURIComponent(requestId)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: submission.payload,
      });
      if (data.resolved !== true || data.request_id !== requestId) throw new Error(errorLabels.invalidResponse);
      if (visible()) consume();
      if (owns()) interactionSubmissionsRef.current.delete(key);
    } catch (error) {
      if (!owns()) return;
      if (!visible()) {
        interactionSubmissionsRef.current.delete(key);
        return;
      }
      if (error instanceof HttpResponseError && error.status === 404 && error.code === "interaction_not_found") {
        consume();
        interactionSubmissionsRef.current.delete(key);
        setOperationNotice({ kind: "warning", message: errorLabels.interactionExpired });
      } else if (error instanceof HttpResponseError && isPreExecutionRejection(error)) {
        interactionSubmissionsRef.current.delete(key);
        setOperationNotice({ kind: "error", message: error.message });
      } else {
        submission.phase = "uncertain";
        setOperationNotice({ kind: "warning", message: errorLabels.interactionUncertain });
      }
    }
  }, [isResourceScopeCurrent]);

  const clearPendingInteractions = useCallback(() => {
    const scope = { ...resourceScopeRef.current };
    const clear = (kind: InteractionKind, requestId: string, payload: string) => {
      const submission = interactionSubmissionsRef.current.get(`${kind}:${requestId}`);
      if (submission) submission.detached = true;
      else void submitInteraction(kind, requestId, payload, scope, true);
    };
    for (const ask of pendingAsksRef.current) clear("ask", ask.request_id, JSON.stringify({ answers: null }));
    for (const request of pendingConfirmsRef.current) clear("confirm", request.request_id,
      JSON.stringify({ action: "deny", deny_reason: errorLabels.interactionCleared, denied_by: "user" }));
    for (const [key, submission] of interactionSubmissionsRef.current) {
      submission.detached = true;
      if (submission.phase === "uncertain") interactionSubmissionsRef.current.delete(key);
    }
    pendingAsksRef.current = [];
    pendingConfirmsRef.current = [];
    setPendingAsks([]);
    setPendingConfirms([]);
  }, [submitInteraction]);

  const refreshSessions = useCallback((options: SessionRefreshOptions = {}): void => {
    const generation = ++sessionsRequestGenerationRef.current;
    const noticeScope = { ...(options.noticeScope ?? resourceScopeRef.current) };
    const failureMessage = options.failureMessage;
    void requestSessionJson("/api/sessions").then((data) => {
      if (sessionsRequestGenerationRef.current !== generation) return;
      if (!Array.isArray(data.sessions) || !data.sessions.every((item) => item && typeof item === "object" && typeof item.id === "string")) {
        throw new Error(errorLabels.invalidResponse);
      }
      setSessions(data.sessions as SessionInfo[]);
    }).catch((error: unknown) => {
      if (sessionsRequestGenerationRef.current !== generation || !isResourceScopeCurrent(noticeScope)) return;
      const detail = error instanceof Error ? error.message : errorLabels.requestFailed;
      setOperationNotice({ kind: "error", message: failureMessage ? `${failureMessage}\n${detail}` : detail });
    });
  }, [isResourceScopeCurrent]);
  const fetchSessions = useCallback((): void => {
    refreshSessions();
  }, [refreshSessions]);
  const refreshAllTags = useCallback((options: SessionRefreshOptions = {}): void => {
    const generation = ++tagsRequestGenerationRef.current;
    const noticeScope = { ...(options.noticeScope ?? resourceScopeRef.current) };
    const failureMessage = options.failureMessage;
    void requestSessionJson("/api/tags").then((data) => {
      if (tagsRequestGenerationRef.current !== generation) return;
      if (!stringList(data.tags)) throw new Error(errorLabels.invalidResponse);
      setAllTags(data.tags);
    }).catch((error: unknown) => {
      if (tagsRequestGenerationRef.current !== generation || !isResourceScopeCurrent(noticeScope)) return;
      const detail = error instanceof Error ? error.message : errorLabels.requestFailed;
      setOperationNotice({ kind: "error", message: failureMessage ? `${failureMessage}\n${detail}` : detail });
    });
  }, [isResourceScopeCurrent]);
  const fetchAllTags = useCallback((): void => {
    refreshAllTags();
  }, [refreshAllTags]);

  const handleMessage = useCallback((message: WSMessage) => {
    if (message.type === WS_IN.SYSTEM) {
      const raw = typeof message.content === "string" ? message.content : JSON.stringify(message.content ?? "");
      try {
        const data = JSON.parse(raw);
        if (data.build_hash) {
          const previous = localStorage.getItem(STORAGE_KEYS.BUILD_HASH) || "";
          localStorage.setItem(STORAGE_KEYS.BUILD_HASH, data.build_hash);
          if (previous && previous !== data.build_hash) window.location.reload();
          return;
        }
        if (data.server_info) {
          setServerInfo(data.server_info);
          return;
        }
        if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
        if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
        if (data.token_usage !== undefined || data.context_tokens !== undefined) return;
        if (data.action === "session_rotated") {
          const oldSid = sessionId;
          setSessionId(data.new_sid);
          localStorage.setItem(STORAGE_KEYS.SESSION_ID, data.new_sid);
          setTokenUsage(0);
          setContextTokens(0);
          setTaskProgress({});
          clearPendingInteractions();
          callbacksRef.current.onSessionRotated?.(data.new_sid, oldSid);
          fetchSessions();
          return;
        }
        // session_title_updated：后端常量 SESSION_TITLE_UPDATED_ACTION 的同值字面量
        // （TS 侧无 import 通道，注释标注来源常量名）
        if (data.action === "session_title_updated") {
          if (typeof data.title === "string" && data.title && message.session_id) {
            setSessions((previous) => previous.map((item) =>
              item.id === message.session_id ? { ...item, title: data.title } : item));
          }
          return;
        }
        if (Array.isArray(data.agents)) {
          setAgents(data.agents);
          return;
        }
        if ("agents" in data) {
          setAgents([]);
          return;
        }
      } catch {
        // 普通 system 文本没有会话元数据副作用。
      }
      if (message.session_id && !sessionId) {
        setSessionId(message.session_id);
        localStorage.setItem(STORAGE_KEYS.SESSION_ID, message.session_id);
      }
      return;
    }
    if (message.type === WS_IN.TASK_PROGRESS) {
      if (message.session_id && message.session_id !== sessionId) return;
      try {
        const data = JSON.parse(message.result ?? "");
        if (data.cleared) {
          setTaskProgress((previous) => {
            if (!Array.isArray(data.cleared) || !data.cleared.length) return {};
            const next = { ...previous };
            for (const id of data.cleared) delete next[id];
            return next;
          });
        } else if (data.task_id) {
          setTaskProgress((previous) => ({ ...previous, [data.task_id]: {
            task_id: data.task_id,
            label: data.label || data.task_id,
            current: data.current ?? 0,
            total: data.total ?? 100,
            percent: data.percent ?? 0,
            status: data.status || "running",
          } }));
        }
      } catch {}
      return;
    }
    if (message.type === WS_IN.CONFIRM_REQUEST && message.request_id) {
      const request: ConfirmRequest = {
        request_id: message.request_id,
        content: typeof message.content === "string" ? message.content : "运行命令?",
        command: (message.args as Record<string, unknown>)?.command as string[] | undefined,
        reason: (message.args as Record<string, unknown>)?.reason as string | undefined,
        tool: message.tool,
        danger_level: message.danger_level,
        args: message.args || {},
      };
      if (!pendingConfirmsRef.current.some((item) => item.request_id === request.request_id)) {
        pendingConfirmsRef.current = [...pendingConfirmsRef.current, request];
        setPendingConfirms(pendingConfirmsRef.current);
      }
      return;
    }
    if (message.type === WS_IN.ASK_REQUEST && message.request_id && Array.isArray(message.questions) && message.questions.length > 0) {
      const request: AskRequest = {
        request_id: message.request_id,
        questions: message.questions,
      };
      if (!pendingAsksRef.current.some((item) => item.request_id === request.request_id)) {
        pendingAsksRef.current = [...pendingAsksRef.current, request];
        setPendingAsks(pendingAsksRef.current);
      }
    }
  }, [clearPendingInteractions, fetchSessions, sessionId]);

  const respondConfirm = useCallback((request: ConfirmRequest | null, action: string, reason?: string, deniedBy?: string): void => {
    if (!request || !pendingConfirmsRef.current.includes(request)) return;
    const body: Record<string, string> = { action };
    if (action === "deny" && reason) {
      body.deny_reason = reason;
      body.denied_by = deniedBy || "user";
    }
    void submitInteraction("confirm", request.request_id, JSON.stringify(body), { ...resourceScopeRef.current }, false);
  }, [submitInteraction]);
  const respondAsk = useCallback((request: AskRequest | null, answers?: AskAnswerItem[] | null): void => {
    if (!request || !pendingAsksRef.current.includes(request)) return;
    void submitInteraction("ask", request.request_id, JSON.stringify({ answers: answers ?? null }), { ...resourceScopeRef.current }, false);
  }, [submitInteraction]);

  const showOperationNotice = useCallback((notice: OperationNotice) => {
    setOperationNotice(notice);
  }, []);
  const dismissOperationNotice = useCallback(() => setOperationNotice(null), []);

  const resetVolatile = useCallback(() => {
    setAgents([]);
    setTokenUsage(0);
    setContextTokens(0);
    setTaskProgress({});
    setInterruptStatus("idle");
    setApprovalModeSyncStatus("loading");
    setOperationNotice(null);
    ignoreStaleRef.current = false;
    clearPendingInteractions();
  }, [clearPendingInteractions]);
  const newChat = useCallback(() => {
    localStorage.removeItem(STORAGE_KEYS.SESSION_ID);
    setSessionId("");
    resetVolatile();
  }, [resetVolatile]);
  const switchSession = useCallback((sid: string) => {
    if (sid === sessionId) return;
    setSessionId(sid);
    resetVolatile();
  }, [resetVolatile, sessionId]);

  const autoTitleSession = useCallback(async (sid: string) => {
    setGeneratingTitleSessions((previous) => new Set(previous).add(sid));
    setOperationNotice(null);
    try {
      const data = await requestSessionJson(`/api/sessions/${sid}/auto-title`, { method: "POST" });
      if (typeof data.title !== "string" || !data.title) throw new Error(errorLabels.invalidResponse);
      const title = data.title;
      setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, title } : item));
      fetchSessions();
    } catch (cause) {
      setOperationNotice({ kind: "error", message: cause instanceof Error ? cause.message : "自动命名失败" });
    } finally {
      setGeneratingTitleSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; });
    }
  }, [fetchSessions]);

  const autoTagSession = useCallback(async (sid: string) => {
    setGeneratingTagSessions((previous) => new Set(previous).add(sid));
    setOperationNotice(null);
    try {
      const data = await requestSessionJson(`/api/sessions/${sid}/auto-tags`, { method: "POST" });
      if (!stringList(data.tags)) throw new Error(errorLabels.invalidResponse);
      const tags = data.tags;
      setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, tags } : item));
      fetchSessions();
      fetchAllTags();
    } catch (cause) {
      setOperationNotice({ kind: "error", message: cause instanceof Error ? cause.message : "自动标签生成失败" });
    } finally {
      setGeneratingTagSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; });
    }
  }, [fetchAllTags, fetchSessions]);

  const regenerateSummary = useCallback(async (sid: string) => {
    setGeneratingSummarySessions((previous) => new Set(previous).add(sid));
    setOperationNotice(null);
    try {
      const data = await requestSessionJson(`/api/sessions/${sid}/regenerate-summary`, { method: "POST" });
      if (data.success !== true) throw new Error(errorLabels.invalidResponse);
      fetchSessions();
    } catch (cause) {
      setOperationNotice({ kind: "error", message: cause instanceof Error ? cause.message : "摘要重新生成失败" });
    } finally {
      setGeneratingSummarySessions((previous) => { const next = new Set(previous); next.delete(sid); return next; });
    }
  }, [fetchSessions]);

  const terminateSession = useCallback(async (sid: string) => {
    if (terminationRequestsRef.current.has(sid)) return;
    const controller = new AbortController();
    const noticeScope = { ...resourceScopeRef.current };
    terminationRequestsRef.current.set(sid, controller);
    setTerminatingSessions((previous) => new Set(previous).add(sid));
    setOperationNotice(null);
    try {
      const response = await requestSessionJson(`/api/sessions/${sid}/terminate`, {
        method: "POST", signal: controller.signal,
      }, null);
      if (terminationRequestsRef.current.get(sid) !== controller) return;
      const data = decodeSessionTerminationResult(response, sid);
      if (!data.terminated) throw new Error(data.error || errorLabels.terminationFailed);
      sessionsRequestGenerationRef.current += 1;
      setSessions((previous) => previous.map((item): SessionInfo =>
        item.id === sid ? { ...item, status: "archived" } : item));
      refreshSessions({ noticeScope, failureMessage: errorLabels.terminationArchivedListRefreshFailed });
      refreshAllTags({ noticeScope, failureMessage: errorLabels.terminationArchivedTagsRefreshFailed });
      const warnings = data.metadata_warnings;
      if (warnings.length && isResourceScopeCurrent(noticeScope)) {
        setOperationNotice({ kind: "warning", message: `${errorLabels.terminationArchivedWithWarnings}\n${warnings.join("\n")}` });
      }
    } catch (cause) {
      if (terminationRequestsRef.current.get(sid) !== controller) return;
      if (isResourceScopeCurrent(noticeScope)) {
        const detail = cause instanceof Error ? cause.message : errorLabels.terminationFailed;
        setOperationNotice({ kind: "error", message: `${detail}\n${errorLabels.terminationUnconfirmed}` });
      }
      refreshSessions({ noticeScope, failureMessage: errorLabels.terminationUnconfirmedListRefreshFailed });
    } finally {
      if (terminationRequestsRef.current.get(sid) === controller) {
        terminationRequestsRef.current.delete(sid);
        setTerminatingSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; });
      }
    }
  }, [isResourceScopeCurrent, refreshAllTags, refreshSessions]);
  const togglePinSession = useCallback((sid: string) => {
    void requestSessionJson(`/api/sessions/${sid}/pin`, { method: "POST" }).then((data) => {
      if (typeof data.pinned !== "boolean") throw new Error(errorLabels.invalidResponse);
      const pinned = data.pinned;
      setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, pinned } : item));
    }).catch((error: unknown) => setOperationNotice({ kind: "error", message: error instanceof Error ? error.message : errorLabels.requestFailed }));
  }, []);
  const renameSession = useCallback((sid: string, title: string) => {
    const trimmed = title.trim().slice(0, 50);
    if (!trimmed) { setRenamingSessionId(null); return; }
    void requestSessionJson(`/api/sessions/${sid}/title`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: trimmed }),
    }).then((data) => {
      if (data.updated !== true || typeof data.title !== "string") throw new Error(errorLabels.invalidResponse);
      const savedTitle = data.title;
      setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, title: savedTitle } : item));
      setRenamingSessionId((current) => current === sid ? null : current);
    }).catch((error: unknown) => setOperationNotice({ kind: "error", message: error instanceof Error ? error.message : errorLabels.requestFailed }));
  }, []);
  const mergeSessions = useCallback(async (sources: string[]): Promise<string | undefined> => {
    const validSources = sources.filter((sid) => sessions.find((item) => item.id === sid)?.status === "archived");
    if (!validSources.length) return undefined;
    setOperationNotice(null);
    try {
      const data = await requestSessionJson("/api/sessions/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources: validSources }),
      });
      if (data.merged !== true || typeof data.session_id !== "string" || !data.session_id) throw new Error(errorLabels.invalidResponse);
      fetchSessions();
      return data.session_id as string;
    } catch (cause) {
      setOperationNotice({ kind: "error", message: cause instanceof Error ? cause.message : "延续会话创建失败" });
      return undefined;
    }
  }, [fetchSessions, sessions]);
  const updateSessionTags = useCallback(async (sid: string, tags: string[]) => {
    const submitted = tags.map((tag) => tag.trim());
    const data = await requestSessionJson(`/api/sessions/${sid}/tags`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags: submitted }),
    });
    if (data.updated !== true || data.session_id !== sid || (data.tags !== null && !stringList(data.tags))) {
      throw new Error(errorLabels.invalidResponse);
    }
    // 正式服务逐项验证后返回 tags=null；仅明确成功时采用本次已验证提交值。
    const saved = data.tags === null ? submitted : data.tags as string[];
    setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, tags: saved } : item));
    return saved;
  }, []);
  const toggleMergeSelect = useCallback((sid: string) => {
    if (sessions.find((item) => item.id === sid)?.status !== "archived") return;
    setSelectedForMerge((previous) => {
      const next = new Set(previous);
      if (next.has(sid)) next.delete(sid); else next.add(sid);
      return next;
    });
  }, [sessions]);

  const sidebarItems = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (query || mergeMode) {
      return sessions
        .filter((item) => !query || (item.title || item.id).toLowerCase().includes(query) || (item.tags || []).some((tag) => tag.toLowerCase().includes(query)))
        .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at))
        .map((session) => ({ kind: "session", session }) as SidebarItem);
    }
    const byId = new Map(sessions.map((item) => [item.id, item]));
    const adjacency = new Map<string, Set<string>>();
    for (const item of sessions) {
      if (!adjacency.has(item.id)) adjacency.set(item.id, new Set());
      for (const parent of item.parents || []) {
        if (!byId.has(parent)) continue;
        adjacency.get(item.id)!.add(parent);
        if (!adjacency.has(parent)) adjacency.set(parent, new Set());
        adjacency.get(parent)!.add(item.id);
      }
      if (item.continuation && byId.has(item.continuation)) {
        adjacency.get(item.id)!.add(item.continuation);
        if (!adjacency.has(item.continuation)) adjacency.set(item.continuation, new Set());
        adjacency.get(item.continuation)!.add(item.id);
      }
    }
    const visited = new Set<string>();
    const result: SidebarItem[] = [];
    for (const item of sessions) {
      if (visited.has(item.id)) continue;
      const component: SessionInfo[] = [];
      const stack = [item.id];
      while (stack.length) {
        const id = stack.pop()!;
        if (visited.has(id)) continue;
        visited.add(id);
        const session = byId.get(id);
        if (session) component.push(session);
        for (const next of adjacency.get(id) || []) if (!visited.has(next)) stack.push(next);
      }
      if (component.length === 1) result.push({ kind: "session", session: component[0] });
      else if (component.length > 1) {
        const root = component.reduce((oldest, candidate) => candidate.created_at < oldest.created_at ? candidate : oldest);
        component.sort((a, b) => (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at));
        result.push({ kind: "cluster", cluster: {
          id: root.id,
          created_at: root.created_at,
          title: component[0].title || `${component[0].id.slice(0, SID_SHORT_LEN)}...`,
          pinned: component.some((member) => member.pinned),
          last_activity_at: Math.max(...component.map((member) => member.last_activity_at || member.created_at)),
          members: component,
        } });
      }
    }
    return result.sort((a, b) => {
      const aPinned = a.kind === "session" ? a.session.pinned : a.cluster.pinned;
      const bPinned = b.kind === "session" ? b.session.pinned : b.cluster.pinned;
      const aTime = a.kind === "session" ? a.session.last_activity_at || a.session.created_at : a.cluster.last_activity_at;
      const bTime = b.kind === "session" ? b.session.last_activity_at || b.session.created_at : b.cluster.last_activity_at;
      return Number(Boolean(bPinned)) - Number(Boolean(aPinned)) || bTime - aTime;
    });
  }, [mergeMode, searchQuery, sessions]);

  useEffect(() => {
    if (!sessionId) return;
    const activeCluster = sidebarItems.find((item) => item.kind === "cluster" && item.cluster.members.some((member) => member.id === sessionId));
    if (activeCluster?.kind === "cluster" && !expandedClusters.has(activeCluster.cluster.id)) {
      setExpandedClusters((previous) => new Set(previous).add(activeCluster.cluster.id));
    }
  }, [expandedClusters, sessionId, setExpandedClusters, sidebarItems]);

  const toggleCluster = useCallback((id: string) => {
    setExpandedClusters((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, [setExpandedClusters]);

  return {
    pendingConfirms, pendingAsks, clearPendingInteractions,
    sessionId, setSessionId, tokenUsage, setTokenUsage, contextTokens, setContextTokens,
    sessions, setSessions, searchQuery, setSearchQuery,
    approvalMode, setApprovalMode, approvalModeSyncStatus, setApprovalModeSyncStatus,
    taskProgress, setTaskProgress,
    dynamicEndpoints: dynamicEndpointResource.snapshot.data ?? [],
    setDynamicEndpoints: dynamicEndpointResource.setData,
    shellResource, cronResource, dynamicEndpointResource,
    resourceSnapshots: {
      shells: shellResource.snapshot,
      cronTasks: cronResource.snapshot,
      dynamicEndpoints: dynamicEndpointResource.snapshot,
    },
    resourceScope: resourceScopeRef.current,
    isResourceScopeCurrent,
    agents, setAgents,
    mergeMode, setMergeMode, selectedForMerge, setSelectedForMerge,
    shells: shellResource.snapshot.data ?? [], setShells: shellResource.setData,
    cronTasks: cronResource.snapshot.data ?? [], setCronTasks: cronResource.setData,
    terminatingSessions, generatingTitleSessions, generatingTagSessions, generatingSummarySessions,
    operationNotice, showOperationNotice, dismissOperationNotice,
    interruptStatus, setInterruptStatus, allTags, ignoreStaleRef,
    fetchSessions, fetchAllTags, handleMessage, respondConfirm, respondAsk,
    newChat, switchSession, autoTitleSession, autoTagSession, regenerateSummary,
    terminateSession, togglePinSession, renamingSessionId, setRenamingSessionId,
    renameSession, mergeSessions, toggleMergeSelect, updateSessionTags,
    sidebarItems, expandedClusters, toggleCluster,
  };
}
