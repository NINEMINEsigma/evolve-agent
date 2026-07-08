import { useReducer, useCallback } from "react";
import type { FileEntry, OpenTab } from "../types";

// ── 语言检测 ──────────────────────────────────────────────

function getLanguageFromPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  const map: Record<string, string> = {
    py: "python", js: "javascript", ts: "typescript", tsx: "typescript",
    jsx: "javascript", html: "html", css: "css", json: "json",
    md: "markdown", yaml: "yaml", yml: "yaml", toml: "toml",
    txt: "plaintext", log: "plaintext", sh: "shell", bat: "bat",
    xml: "xml", sql: "sql", rs: "rust", go: "go", java: "java",
    c: "c", cpp: "cpp", h: "c", hpp: "cpp",
  };
  return map[ext] || "plaintext";
}

// ── State ──────────────────────────────────────────────────

interface AgentspaceState {
  dirContents: Record<string, FileEntry[]>;
  openTabs: OpenTab[];
  activeTabId: string | null;
  loading: boolean;
  error: string | null;
  locked: boolean;
  currentDir: string;
}

type Action =
  | { type: "LOAD_DIR"; payload: { path: string; entries: FileEntry[] } }
  | { type: "UNLOAD_DIR"; payload: string }
  | { type: "OPEN_TAB"; payload: OpenTab }
  | { type: "CLOSE_TAB"; payload: string }
  | { type: "SET_ACTIVE_TAB"; payload: string }
  | { type: "UPDATE_CONTENT"; payload: { id: string; content: string } }
  | { type: "SAVE_TAB"; payload: string }
  | { type: "RENAME_TAB"; payload: { oldPath: string; newPath: string; newName: string } }
  | { type: "SET_LOADING"; payload: boolean }
  | { type: "SET_ERROR"; payload: string | null }
  | { type: "SET_LOCKED"; payload: boolean }
  | { type: "SET_CURRENT_DIR"; payload: string };

function reducer(state: AgentspaceState, action: Action): AgentspaceState {
  switch (action.type) {
    case "LOAD_DIR": {
      const next = { ...state.dirContents, [action.payload.path]: action.payload.entries };
      return { ...state, dirContents: next, loading: false, error: null };
    }
    case "UNLOAD_DIR": {
      const next = { ...state.dirContents };
      delete next[action.payload];
      return { ...state, dirContents: next };
    }
    case "OPEN_TAB": {
      const existing = state.openTabs.find((t) => t.path === action.payload.path);
      if (existing) return { ...state, activeTabId: existing.id };
      return {
        ...state,
        openTabs: [...state.openTabs, action.payload],
        activeTabId: action.payload.id,
      };
    }
    case "CLOSE_TAB": {
      const tabs = state.openTabs.filter((t) => t.id !== action.payload);
      let activeId = state.activeTabId;
      if (state.activeTabId === action.payload) {
        activeId = tabs.length > 0 ? tabs[tabs.length - 1].id : null;
      }
      return { ...state, openTabs: tabs, activeTabId: activeId };
    }
    case "SET_ACTIVE_TAB":
      return { ...state, activeTabId: action.payload };
    case "UPDATE_CONTENT": {
      const tabs = state.openTabs.map((t) =>
        t.id === action.payload.id ? { ...t, content: action.payload.content, isDirty: action.payload.content !== t.originalContent } : t
      );
      return { ...state, openTabs: tabs };
    }
    case "SAVE_TAB": {
      const tabs = state.openTabs.map((t) =>
        t.id === action.payload ? { ...t, originalContent: t.content, isDirty: false } : t
      );
      return { ...state, openTabs: tabs };
    }
    case "RENAME_TAB": {
      const tabs = state.openTabs.map((t) =>
        t.path === action.payload.oldPath ? { ...t, path: action.payload.newPath, name: action.payload.newName } : t
      );
      return { ...state, openTabs: tabs };
    }
    case "SET_LOADING":
      return { ...state, loading: action.payload };
    case "SET_ERROR":
      return { ...state, error: action.payload, loading: false };
    case "SET_LOCKED":
      return { ...state, locked: action.payload };
    case "SET_CURRENT_DIR":
      return { ...state, currentDir: action.payload };
    default:
      return state;
  }
}

const initialState: AgentspaceState = {
  dirContents: {},
  openTabs: [],
  activeTabId: null,
  loading: false,
  error: null,
  locked: false,
  currentDir: "",
};

function genId(): string {
  return Math.random().toString(36).substring(2, 10);
}

// ── API helpers ────────────────────────────────────────────

async function apiGet(path: string): Promise<any> {
  const res = await fetch(path);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiPost(path: string, body: Record<string, string>): Promise<any> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Hook ───────────────────────────────────────────────────

export function useAgentspace() {
  const [state, dispatch] = useReducer(reducer, initialState);

  /** 加载指定路径的目录内容 */
  const loadDirectory = useCallback(async (path: string) => {
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const data = await apiGet(`/api/agentspace/list?path=${encodeURIComponent(path)}`);
      dispatch({ type: "LOAD_DIR", payload: { path, entries: data.entries || [] } });
      dispatch({ type: "SET_CURRENT_DIR", payload: path });
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, []);

  /** 展开文件夹：如果未缓存则加载，已缓存则直接展开；折叠时移除缓存 */
  const toggleDir = useCallback(async (path: string) => {
    if (state.dirContents[path]) {
      // 已缓存 → 折叠
      dispatch({ type: "UNLOAD_DIR", payload: path });
    } else {
      // 未缓存 → 加载并展开
      await loadDirectory(path);
    }
  }, [state.dirContents, loadDirectory]);

  /** 刷新当前目录 */
  const refresh = useCallback(async () => {
    await loadDirectory(state.currentDir);
  }, [state.currentDir, loadDirectory]);

  const openFile = useCallback(async (path: string) => {
    const existing = state.openTabs.find((t) => t.path === path);
    if (existing) {
      dispatch({ type: "SET_ACTIVE_TAB", payload: existing.id });
      return;
    }
    dispatch({ type: "SET_LOADING", payload: true });
    try {
      const data = await apiGet(`/api/agentspace/read?path=${encodeURIComponent(path)}`);
      const name = path.split("/").pop() || path;
      const tab: OpenTab = {
        id: genId(),
        path,
        name,
        content: data.content,
        originalContent: data.content,
        isDirty: false,
        language: getLanguageFromPath(path),
      };
      dispatch({ type: "OPEN_TAB", payload: tab });
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [state.openTabs]);

  const saveFile = useCallback(async (tabId: string) => {
    const tab = state.openTabs.find((t) => t.id === tabId);
    if (!tab || !tab.isDirty) return;
    try {
      await apiPost("/api/agentspace/write", { path: tab.path, content: tab.content });
      dispatch({ type: "SAVE_TAB", payload: tabId });
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [state.openTabs]);

  const closeTab = useCallback((tabId: string) => {
    dispatch({ type: "CLOSE_TAB", payload: tabId });
  }, []);

  const setActiveTab = useCallback((tabId: string) => {
    dispatch({ type: "SET_ACTIVE_TAB", payload: tabId });
  }, []);

  const updateContent = useCallback((tabId: string, content: string) => {
    dispatch({ type: "UPDATE_CONTENT", payload: { id: tabId, content } });
  }, []);

  const createFile = useCallback(async (parentDir: string, name: string) => {
    const path = parentDir ? `${parentDir}/${name}` : name;
    try {
      await apiPost("/api/agentspace/write", { path, content: "" });
      await loadDirectory(parentDir);
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [loadDirectory]);

  const createFolder = useCallback(async (parentDir: string, name: string) => {
    const path = parentDir ? `${parentDir}/${name}` : name;
    try {
      await apiPost("/api/agentspace/mkdir", { path });
      await loadDirectory(parentDir);
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [loadDirectory]);

  const deletePath = useCallback(async (path: string) => {
    try {
      await apiPost("/api/agentspace/delete", { path });
      const relatedTab = state.openTabs.find((t) => t.path === path || t.path.startsWith(path + "/"));
      if (relatedTab) dispatch({ type: "CLOSE_TAB", payload: relatedTab.id });
      const parentDir = path.substring(0, path.lastIndexOf("/"));
      await loadDirectory(parentDir);
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [state.openTabs, loadDirectory]);

  const renamePath = useCallback(async (oldPath: string, newName: string) => {
    const parentDir = oldPath.substring(0, oldPath.lastIndexOf("/"));
    const newPath = parentDir ? `${parentDir}/${newName}` : newName;
    try {
      await apiPost("/api/agentspace/rename", { oldPath, newPath });
      dispatch({ type: "RENAME_TAB", payload: { oldPath, newPath, newName } });
      await loadDirectory(parentDir);
    } catch (e: any) {
      dispatch({ type: "SET_ERROR", payload: e.message });
    }
  }, [loadDirectory]);

  const loadLockStatus = useCallback(async () => {
    try {
      const data = await apiGet("/api/agentspace/lock");
      dispatch({ type: "SET_LOCKED", payload: data.locked });
    } catch {
      // 静默失败
    }
  }, []);

  return {
    dirContents: state.dirContents,
    openTabs: state.openTabs,
    activeTabId: state.activeTabId,
    loading: state.loading,
    error: state.error,
    locked: state.locked,
    currentDir: state.currentDir,
    loadDirectory,
    openFile,
    saveFile,
    closeTab,
    setActiveTab,
    updateContent,
    createFile,
    createFolder,
    deletePath,
    renamePath,
    toggleDir,
    refresh,
    loadLockStatus,
  };
}