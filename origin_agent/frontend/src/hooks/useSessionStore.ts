import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import type {
  ApprovalMode,
  ApprovalModeSyncStatus,
  AskRequest,
  ClipboardDisplay,
  ConfirmRequest,
  CronTask,
  DynamicEndpoint,
  InterruptStatus,
  SessionInfo,
  ShellInfo,
  SidebarItem,
  TaskProgress,
  WSMessage,
} from "../types";
import { STORAGE_KEYS } from "../constants/storage";
import { SID_SHORT_LEN } from "../constants/session";
import { WS_IN } from "../constants/ws";

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
  clipboardDisplays: Record<string, ClipboardDisplay>;
  setClipboardDisplays: React.Dispatch<React.SetStateAction<Record<string, ClipboardDisplay>>>;
  dynamicEndpoints: DynamicEndpoint[];
  setDynamicEndpoints: React.Dispatch<React.SetStateAction<DynamicEndpoint[]>>;
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
  interruptStatus: InterruptStatus;
  setInterruptStatus: React.Dispatch<React.SetStateAction<InterruptStatus>>;
  allTags: string[];
  ignoreStaleRef: React.MutableRefObject<boolean>;
  fetchSessions: () => void;
  fetchAllTags: () => void;
  handleMessage: (message: WSMessage) => void;
  respondConfirm: (request: ConfirmRequest | null, action: string, reason?: string, deniedBy?: string) => void;
  respondAsk: (request: AskRequest | null, option?: string, customText?: string) => void;
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
  const [sessionId, setSessionId] = useState("");
  const [tokenUsage, setTokenUsage] = useState(0);
  const [contextTokens, setContextTokens] = useState(0);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>("manual");
  const [approvalModeSyncStatus, setApprovalModeSyncStatus] = useState<ApprovalModeSyncStatus>("loading");
  const [taskProgress, setTaskProgress] = useState<Record<string, TaskProgress>>({});
  const [clipboardDisplays, setClipboardDisplays] = useState<Record<string, ClipboardDisplay>>({});
  const [dynamicEndpoints, setDynamicEndpoints] = useState<DynamicEndpoint[]>([]);
  const [agents, setAgents] = useState<string[]>([]);
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set());
  const [shells, setShells] = useState<ShellInfo[]>([]);
  const [cronTasks, setCronTasks] = useState<CronTask[]>([]);
  const [terminatingSessions, setTerminatingSessions] = useState<Set<string>>(new Set());
  const [generatingTitleSessions, setGeneratingTitleSessions] = useState<Set<string>>(new Set());
  const [generatingTagSessions, setGeneratingTagSessions] = useState<Set<string>>(new Set());
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

  const pendingAsksRef = useRef<AskRequest[]>([]);
  const pendingConfirmsRef = useRef<ConfirmRequest[]>([]);
  const callbacksRef = useRef(callbacks);
  const ignoreStaleRef = useRef(false);
  useEffect(() => { pendingAsksRef.current = pendingAsks; }, [pendingAsks]);
  useEffect(() => { pendingConfirmsRef.current = pendingConfirms; }, [pendingConfirms]);
  useEffect(() => { callbacksRef.current = callbacks; }, [callbacks]);

  const clearPendingInteractions = useCallback(() => {
    for (const ask of pendingAsksRef.current) {
      fetch(`/api/ask/${ask.request_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ option: null, custom_text: null }),
      }).catch(() => {});
    }
    for (const request of pendingConfirmsRef.current) {
      fetch(`/api/confirm/${request.request_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "deny", deny_reason: "会话中断或切换", denied_by: "user" }),
      }).catch(() => {});
    }
    setPendingAsks([]);
    setPendingConfirms([]);
  }, []);

  const fetchSessions = useCallback(() => {
    fetch("/api/sessions").then((response) => response.json())
      .then((data) => setSessions(data.sessions || [])).catch(() => {});
  }, []);
  const fetchAllTags = useCallback(() => {
    fetch("/api/tags").then((response) => response.json())
      .then((data) => setAllTags(data.tags || [])).catch(() => {});
  }, []);

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
          setClipboardDisplays({});
          setDynamicEndpoints([]);
          clearPendingInteractions();
          callbacksRef.current.onSessionRotated?.(data.new_sid, oldSid);
          fetchSessions();
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
    if (message.type === WS_IN.CLIPBOARD_DISPLAY) {
      if (message.session_id && message.session_id !== sessionId) return;
      try {
        const data = JSON.parse(message.result ?? "");
        if (data.cleared) {
          setClipboardDisplays((previous) => {
            if (!Array.isArray(data.cleared) || !data.cleared.length) return {};
            const next = { ...previous };
            for (const id of data.cleared) delete next[id];
            return next;
          });
        } else if (data.display_id) {
          setClipboardDisplays((previous) => ({ ...previous, [data.display_id]: {
            display_id: data.display_id,
            label: data.label || data.display_id,
            content: data.content ?? "",
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
      setPendingConfirms((previous) => previous.some((item) => item.request_id === request.request_id)
        ? previous : [...previous, request]);
      return;
    }
    if (message.type === WS_IN.ASK_REQUEST && message.request_id && message.question) {
      const request: AskRequest = {
        request_id: message.request_id,
        question: message.question,
        detail: message.detail,
        options: message.options,
      };
      setPendingAsks((previous) => previous.some((item) => item.request_id === request.request_id)
        ? previous : [...previous, request]);
    }
  }, [clearPendingInteractions, fetchSessions, sessionId]);

  const respondConfirm = useCallback((request: ConfirmRequest | null, action: string, reason?: string, deniedBy?: string) => {
    if (!request) return;
    const body: Record<string, string> = { action };
    if (action === "deny" && reason) {
      body.deny_reason = reason;
      body.denied_by = deniedBy || "user";
    }
    fetch(`/api/confirm/${request.request_id}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).catch(() => {});
    setPendingConfirms((previous) => previous.filter((item) => item.request_id !== request.request_id));
  }, []);
  const respondAsk = useCallback((request: AskRequest | null, option?: string, customText?: string) => {
    if (!request) return;
    fetch(`/api/ask/${request.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option: option ?? null, custom_text: customText ?? null }),
    }).catch(() => {});
    setPendingAsks((previous) => previous.filter((item) => item.request_id !== request.request_id));
  }, []);

  const resetVolatile = useCallback(() => {
    setAgents([]);
    setTokenUsage(0);
    setContextTokens(0);
    setTaskProgress({});
    setClipboardDisplays({});
    setDynamicEndpoints([]);
    setInterruptStatus("idle");
    setApprovalModeSyncStatus("loading");
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

  const autoTitleSession = useCallback((sid: string) => {
    setGeneratingTitleSessions((previous) => new Set(previous).add(sid));
    fetch(`/api/sessions/${sid}/auto-title`, { method: "POST" }).then((response) => response.json())
      .then((data) => {
        if (data.title) {
          setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, title: data.title } : item));
          fetchSessions();
        }
      })
      .catch(() => {})
      .finally(() => setGeneratingTitleSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; }));
  }, [fetchSessions]);
  const autoTagSession = useCallback((sid: string) => {
    setGeneratingTagSessions((previous) => new Set(previous).add(sid));
    fetch(`/api/sessions/${sid}/auto-tags`, { method: "POST" }).then((response) => response.json())
      .then((data) => {
        if (Array.isArray(data.tags)) {
          setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, tags: data.tags } : item));
          fetchSessions();
          fetchAllTags();
        }
      })
      .catch(() => {})
      .finally(() => setGeneratingTagSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; }));
  }, [fetchAllTags, fetchSessions]);
  const regenerateSummary = useCallback((sid: string) => {
    setGeneratingTitleSessions((previous) => new Set(previous).add(sid));
    fetch(`/api/sessions/${sid}/regenerate-summary`, { method: "POST" }).then(() => fetchSessions()).catch(() => {})
      .finally(() => setGeneratingTitleSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; }));
  }, [fetchSessions]);
  const terminateSession = useCallback((sid: string) => {
    setTerminatingSessions((previous) => new Set(previous).add(sid));
    fetch(`/api/sessions/${sid}/terminate`, { method: "POST" }).then(() => fetchSessions()).catch(() => {})
      .finally(() => setTerminatingSessions((previous) => { const next = new Set(previous); next.delete(sid); return next; }));
  }, [fetchSessions]);
  const togglePinSession = useCallback((sid: string) => {
    fetch(`/api/sessions/${sid}/pin`, { method: "POST" }).then((response) => response.json())
      .then((data) => setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, pinned: data.pinned } : item)))
      .catch(() => {});
  }, []);
  const renameSession = useCallback((sid: string, title: string) => {
    const trimmed = title.trim().slice(0, 50);
    if (!trimmed) { setRenamingSessionId(null); return; }
    fetch(`/api/sessions/${sid}/title`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: trimmed }),
    }).then((response) => response.json())
      .then((data) => { if (data.updated) setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, title: data.title } : item)); })
      .catch(() => {}).finally(() => setRenamingSessionId(null));
  }, []);
  const mergeSessions = useCallback((sources: string[]): Promise<string | undefined> => {
    const validSources = sources.filter((sid) => sessions.find((item) => item.id === sid)?.status === "archived");
    if (!validSources.length) return Promise.resolve(undefined);
    return fetch("/api/sessions/merge", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sources: validSources }),
    }).then((response) => response.json()).then((data) => {
      if (data.session_id) fetchSessions();
      return data.session_id as string | undefined;
    }).catch(() => undefined);
  }, [fetchSessions, sessions]);
  const updateSessionTags = useCallback(async (sid: string, tags: string[]) => {
    const valid = tags.map((tag) => tag.trim()).filter((tag) => /^[\u4e00-\u9fa5]{1,5}$/.test(tag) || /^[a-zA-Z]{1,10}$/.test(tag));
    const response = await fetch(`/api/sessions/${sid}/tags`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags: valid }),
    });
    const data = await response.json().catch(() => ({}));
    if (data.updated) setSessions((previous) => previous.map((item) => item.id === sid ? { ...item, tags: data.tags || valid } : item));
    return data.tags || valid;
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
    taskProgress, setTaskProgress, clipboardDisplays, setClipboardDisplays,
    dynamicEndpoints, setDynamicEndpoints, agents, setAgents,
    mergeMode, setMergeMode, selectedForMerge, setSelectedForMerge,
    shells, setShells, cronTasks, setCronTasks,
    terminatingSessions, generatingTitleSessions, generatingTagSessions,
    interruptStatus, setInterruptStatus, allTags, ignoreStaleRef,
    fetchSessions, fetchAllTags, handleMessage, respondConfirm, respondAsk,
    newChat, switchSession, autoTitleSession, autoTagSession, regenerateSummary,
    terminateSession, togglePinSession, renamingSessionId, setRenamingSessionId,
    renameSession, mergeSessions, toggleMergeSelect, updateSessionTags,
    sidebarItems, expandedClusters, toggleCluster,
  };
}
