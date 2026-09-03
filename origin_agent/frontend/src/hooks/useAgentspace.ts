import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import type {
  AgentspaceErrorState,
  AgentspaceEvent,
  DirectoryStateMap,
  EntrySelection,
  ExternalConflict,
  FileEntry,
  FileLock,
  FileSnapshot,
  OpenTab,
  SyncState,
  TrashEntry,
} from "../types";
import * as api from "../services/agentspaceApi";
import { AgentspaceApiError } from "../services/agentspaceApi";
import {
  baseName,
  isPathWithin,
  joinPath,
  parentPath,
  rewritePathPrefix,
  sortEntries,
} from "../utils/agentspacePath";

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

function genId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

function lockForPath(locks: FileLock[], path: string): FileLock[] {
  return locks.filter((lock) =>
    lock.path === path || (lock.recursive && isPathWithin(path, lock.path)),
  );
}

interface AgentspaceState {
  directories: DirectoryStateMap;
  expandedPaths: Set<string>;
  selection: EntrySelection;
  openTabs: OpenTab[];
  activeTabId: string | null;
  locks: FileLock[];
  trashEntries: TrashEntry[];
  trashExpanded: boolean;
  syncState: SyncState;
  error: AgentspaceErrorState;
}

type Action =
  | { type: "DIR_LOADING"; path: string }
  | { type: "DIR_LOADED"; path: string; entries: FileEntry[] }
  | { type: "DIR_ERROR"; path: string; message: string }
  | { type: "SET_EXPANDED"; path: string; expanded: boolean }
  | { type: "SELECT"; selection: EntrySelection }
  | { type: "OPEN_TAB"; tab: OpenTab }
  | { type: "SET_ACTIVE"; id: string }
  | { type: "CLOSE_TAB"; id: string }
  | { type: "UPDATE_CONTENT"; id: string; content: string }
  | { type: "APPLY_SNAPSHOT"; id: string; snapshot: FileSnapshot }
  | { type: "SET_CONFLICT"; id: string; conflict: ExternalConflict }
  | { type: "REWRITE_PATH"; oldPath: string; newPath: string }
  | { type: "REMOVE_PATH"; path: string }
  | { type: "SET_LOCKS"; locks: FileLock[] }
  | { type: "SET_TRASH"; entries: TrashEntry[] }
  | { type: "SET_TRASH_EXPANDED"; expanded: boolean }
  | { type: "SET_SYNC"; state: SyncState }
  | { type: "SET_ERROR"; error: AgentspaceErrorState }
  | { type: "USE_DISK"; id: string }
  | { type: "DISCARD_DELETED"; id: string };

const initialState: AgentspaceState = {
  directories: {},
  expandedPaths: new Set(),
  selection: null,
  openTabs: [],
  activeTabId: null,
  locks: [],
  trashEntries: [],
  trashExpanded: false,
  syncState: "connecting",
  error: null,
};

function reducer(state: AgentspaceState, action: Action): AgentspaceState {
  switch (action.type) {
    case "DIR_LOADING":
      return {
        ...state,
        directories: {
          ...state.directories,
          [action.path]: {
            entries: state.directories[action.path]?.entries || [],
            loading: true,
            error: null,
          },
        },
      };
    case "DIR_LOADED":
      return {
        ...state,
        directories: {
          ...state.directories,
          [action.path]: {
            entries: sortEntries(action.entries),
            loading: false,
            error: null,
          },
        },
      };
    case "DIR_ERROR":
      return {
        ...state,
        directories: {
          ...state.directories,
          [action.path]: {
            entries: state.directories[action.path]?.entries || [],
            loading: false,
            error: action.message,
          },
        },
      };
    case "SET_EXPANDED": {
      const expanded = new Set(state.expandedPaths);
      if (action.expanded) expanded.add(action.path);
      else expanded.delete(action.path);
      return { ...state, expandedPaths: expanded };
    }
    case "SELECT":
      return { ...state, selection: action.selection };
    case "OPEN_TAB": {
      const existing = state.openTabs.find((tab) => tab.path === action.tab.path);
      if (existing) return { ...state, activeTabId: existing.id };
      return {
        ...state,
        openTabs: [...state.openTabs, action.tab],
        activeTabId: action.tab.id,
      };
    }
    case "SET_ACTIVE":
      return { ...state, activeTabId: action.id };
    case "CLOSE_TAB": {
      const index = state.openTabs.findIndex((tab) => tab.id === action.id);
      if (index < 0) return state;
      const tabs = state.openTabs.filter((tab) => tab.id !== action.id);
      let activeTabId = state.activeTabId;
      if (activeTabId === action.id) {
        activeTabId = tabs[index]?.id || tabs[index - 1]?.id || null;
      }
      return { ...state, openTabs: tabs, activeTabId };
    }
    case "UPDATE_CONTENT":
      return {
        ...state,
        openTabs: state.openTabs.map((tab) =>
          tab.id === action.id
            ? {
                ...tab,
                content: action.content,
                isDirty: action.content !== tab.originalContent,
              }
            : tab,
        ),
      };
    case "APPLY_SNAPSHOT":
      return {
        ...state,
        openTabs: state.openTabs.map((tab) =>
          tab.id === action.id
            ? {
                ...tab,
                path: action.snapshot.path,
                name: baseName(action.snapshot.path),
                content: action.snapshot.content,
                originalContent: action.snapshot.content,
                version: action.snapshot.version,
                modifiedNs: action.snapshot.modified_ns,
                isDirty: false,
                conflict: null,
              }
            : tab,
        ),
      };
    case "SET_CONFLICT":
      return {
        ...state,
        openTabs: state.openTabs.map((tab) =>
          tab.id === action.id ? { ...tab, conflict: action.conflict } : tab,
        ),
      };
    case "REWRITE_PATH": {
      const directories: DirectoryStateMap = {};
      for (const [path, directory] of Object.entries(state.directories)) {
        const nextKey = isPathWithin(path, action.oldPath)
          ? rewritePathPrefix(path, action.oldPath, action.newPath)
          : path;
        directories[nextKey] = {
          ...directory,
          entries: sortEntries(directory.entries.map((entry) => {
            if (!isPathWithin(entry.path, action.oldPath)) return entry;
            const nextPath = rewritePathPrefix(entry.path, action.oldPath, action.newPath);
            return { ...entry, path: nextPath, name: baseName(nextPath) };
          })),
        };
      }
      const expandedPaths = new Set(
        [...state.expandedPaths].map((path) =>
          isPathWithin(path, action.oldPath)
            ? rewritePathPrefix(path, action.oldPath, action.newPath)
            : path,
        ),
      );
      const selection = state.selection && isPathWithin(state.selection.path, action.oldPath)
        ? { ...state.selection, path: rewritePathPrefix(state.selection.path, action.oldPath, action.newPath) }
        : state.selection;
      const openTabs = state.openTabs.map((tab) => {
        if (!isPathWithin(tab.path, action.oldPath)) return tab;
        const path = rewritePathPrefix(tab.path, action.oldPath, action.newPath);
        return { ...tab, path, name: baseName(path) };
      });
      return { ...state, directories, expandedPaths, selection, openTabs };
    }
    case "REMOVE_PATH": {
      const removedIds = new Set(
        state.openTabs.filter((tab) => isPathWithin(tab.path, action.path)).map((tab) => tab.id),
      );
      const openTabs = state.openTabs.filter((tab) => !removedIds.has(tab.id));
      const activeTabId = state.activeTabId && removedIds.has(state.activeTabId)
        ? openTabs[0]?.id || null
        : state.activeTabId;
      const directories = Object.fromEntries(
        Object.entries(state.directories).filter(([path]) => !isPathWithin(path, action.path)),
      );
      const expandedPaths = new Set(
        [...state.expandedPaths].filter((path) => !isPathWithin(path, action.path)),
      );
      const selection = state.selection && isPathWithin(state.selection.path, action.path)
        ? null
        : state.selection;
      return { ...state, openTabs, activeTabId, directories, expandedPaths, selection };
    }
    case "SET_LOCKS": {
      const openTabs = state.openTabs.map((tab) => {
        const matches = lockForPath(action.locks, tab.path);
        return {
          ...tab,
          isLocked: matches.length > 0,
          lockOwners: matches.flatMap((lock) => lock.owners),
        };
      });
      return { ...state, locks: action.locks, openTabs };
    }
    case "SET_TRASH":
      return { ...state, trashEntries: action.entries };
    case "SET_TRASH_EXPANDED":
      return { ...state, trashExpanded: action.expanded };
    case "SET_SYNC":
      return { ...state, syncState: action.state };
    case "SET_ERROR":
      return { ...state, error: action.error };
    case "USE_DISK": {
      const tab = state.openTabs.find((item) => item.id === action.id);
      if (!tab?.conflict || tab.conflict.kind !== "modified") return state;
      return {
        ...state,
        openTabs: state.openTabs.map((item) =>
          item.id === action.id
            ? {
                ...item,
                content: tab.conflict!.diskContent || "",
                originalContent: tab.conflict!.diskContent || "",
                version: tab.conflict!.diskVersion || "",
                isDirty: false,
                conflict: null,
              }
            : item,
        ),
      };
    }
    case "DISCARD_DELETED":
      return reducer(state, { type: "CLOSE_TAB", id: action.id });
    default:
      return state;
  }
}

export interface UseAgentspaceResult {
  directories: DirectoryStateMap;
  expandedPaths: Set<string>;
  selection: EntrySelection;
  openTabs: OpenTab[];
  activeTabId: string | null;
  locks: FileLock[];
  trashEntries: TrashEntry[];
  trashExpanded: boolean;
  syncState: SyncState;
  error: AgentspaceErrorState;
  hasDirtyTabs: boolean;
  loadDirectory(path: string, force?: boolean): Promise<void>;
  refreshExpandedDirectories(): Promise<void>;
  toggleDirectory(path: string): Promise<void>;
  selectEntry(entry: FileEntry): void;
  openFile(path: string): Promise<void>;
  setActiveTab(id: string): void;
  updateContent(id: string, content: string): void;
  saveFile(id: string, expectedVersionOverride?: string | null): Promise<boolean>;
  closeCleanTab(id: string): void;
  discardAndCloseTab(id: string): void;
  createFile(parent: string, name: string): Promise<void>;
  createFolder(parent: string, name: string): Promise<void>;
  renamePath(path: string, newName: string): Promise<void>;
  movePathToTrash(path: string): Promise<void>;
  setTrashExpanded(expanded: boolean): void;
  restoreTrashEntry(entryId: string): Promise<void>;
  purgeTrashEntry(entryId: string): Promise<void>;
  emptyTrash(): Promise<void>;
  resolveConflictWithDisk(tabId: string): void;
  resolveConflictWithLocal(tabId: string): Promise<boolean>;
  recreateDeletedConflict(tabId: string): Promise<boolean>;
  discardDeletedConflict(tabId: string): void;
  clearError(): void;
}

export function useAgentspace(): UseAgentspaceResult {
  const [state, rawDispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  const dispatch = useCallback((action: Action) => {
    stateRef.current = reducer(stateRef.current, action);
    rawDispatch(action);
  }, []);
  const requestEpochRef = useRef<Record<string, number>>({});
  const generationRef = useRef<Record<string, number>>({});
  const globalGenerationRef = useRef(0);
  const lastSequenceRef = useRef(0);
  const operationVersionsRef = useRef(new Map<string, { path: string; version: string | null; sequence: number }>());
  const pathVersionsRef = useRef(new Map<string, string | null>());
  const pendingOperationsRef = useRef(new Set<string>());
  const pendingWriteVersionsRef = useRef(new Map<string, string>());

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const nextEpoch = useCallback((key: string) => {
    const next = (requestEpochRef.current[key] || 0) + 1;
    requestEpochRef.current[key] = next;
    return next;
  }, []);

  const generation = useCallback((path: string) =>
    (generationRef.current[path] || 0) + globalGenerationRef.current, []);

  const bumpGeneration = useCallback((path: string | null) => {
    if (path === null) return;
    generationRef.current[path] = (generationRef.current[path] || 0) + 1;
    const parent = parentPath(path);
    generationRef.current[parent] = (generationRef.current[parent] || 0) + 1;
  }, []);

  const setError = useCallback((message: string, retry: (() => Promise<void>) | null = null) => {
    dispatch({ type: "SET_ERROR", error: { message, retry } });
  }, []);

  const loadDirectory: UseAgentspaceResult["loadDirectory"] = useCallback(async (path: string, force = false) => {
    const key = `dir:${path}`;
    if (!force && stateRef.current.directories[path]?.loading) return;
    const epoch = nextEpoch(key);
    const generationAtStart = generation(path);
    const sequenceAtStart = lastSequenceRef.current;
    dispatch({ type: "DIR_LOADING", path });
    try {
      const entries = await api.listDirectory(path);
      if (
        requestEpochRef.current[key] !== epoch
        || generation(path) !== generationAtStart
        || lastSequenceRef.current > sequenceAtStart
      ) return;
      dispatch({ type: "DIR_LOADED", path, entries: sortEntries(entries) });
    } catch (error) {
      if (requestEpochRef.current[key] !== epoch) return;
      const message = error instanceof Error ? error.message : "目录加载失败";
      dispatch({ type: "DIR_ERROR", path, message });
      setError(message, () => loadDirectory(path, true));
    }
  }, [generation, nextEpoch, setError]);

  const loadTrashEntries: () => Promise<void> = useCallback(async () => {
    const key = "trash";
    const epoch = nextEpoch(key);
    try {
      const entries = await api.listTrash();
      if (requestEpochRef.current[key] === epoch) {
        dispatch({ type: "SET_TRASH", entries });
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "垃圾桶加载失败", loadTrashEntries);
    }
  }, [nextEpoch, setError]);

  const loadLocks: () => Promise<void> = useCallback(async () => {
    try {
      dispatch({ type: "SET_LOCKS", locks: await api.getLocks() });
    } catch (error) {
      setError(error instanceof Error ? error.message : "文件锁状态加载失败", loadLocks);
    }
  }, [setError]);

  const refreshExpandedDirectories = useCallback(async () => {
    const paths = ["", ...stateRef.current.expandedPaths];
    await Promise.all([...new Set(paths)].map((path) => loadDirectory(path, true)));
  }, [loadDirectory]);

  const toggleDirectory = useCallback(async (path: string) => {
    const expanded = stateRef.current.expandedPaths.has(path);
    dispatch({ type: "SET_EXPANDED", path, expanded: !expanded });
    if (!expanded) await loadDirectory(path, true);
  }, [loadDirectory]);

  const selectEntry = useCallback((entry: FileEntry) => {
    dispatch({ type: "SELECT", selection: { path: entry.path, kind: entry.kind } });
  }, []);

  const openFile: UseAgentspaceResult["openFile"] = useCallback(async (path: string) => {
    const existing = stateRef.current.openTabs.find((tab) => tab.path === path);
    if (existing) {
      dispatch({ type: "SET_ACTIVE", id: existing.id });
      return;
    }
    const key = `file:${path}`;
    const epoch = nextEpoch(key);
    const generationAtStart = generation(path);
    const sequenceAtStart = lastSequenceRef.current;
    try {
      const snapshot = await api.readFile(path);
      if (
        requestEpochRef.current[key] !== epoch
        || generation(path) !== generationAtStart
        || lastSequenceRef.current > sequenceAtStart
      ) return;
      const matchingLocks = lockForPath(stateRef.current.locks, path);
      dispatch({
        type: "OPEN_TAB",
        tab: {
          id: genId(),
          path,
          name: baseName(path),
          content: snapshot.content,
          originalContent: snapshot.content,
          isDirty: false,
          language: getLanguageFromPath(path),
          version: snapshot.version,
          modifiedNs: snapshot.modified_ns,
          isLocked: matchingLocks.length > 0,
          lockOwners: matchingLocks.flatMap((lock) => lock.owners),
          conflict: null,
        },
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : "文件打开失败", () => openFile(path));
    }
  }, [generation, nextEpoch, setError]);

  const saveFile: UseAgentspaceResult["saveFile"] = useCallback(async (
    id: string,
    expectedVersionOverride?: string | null,
  ): Promise<boolean> => {
    const tab = stateRef.current.openTabs.find((item) => item.id === id);
    if (!tab || (!tab.isDirty && expectedVersionOverride === undefined)) return true;
    if (tab.isLocked) {
      setError(
        "该文件正在被 Agent 使用，请等待当前回复结束。",
        async () => { await saveFile(id, expectedVersionOverride); },
      );
      return false;
    }
    if (tab.conflict && expectedVersionOverride === undefined) {
      setError("请先在冲突比较窗口中选择要保留的版本。", null);
      return false;
    }
    const key = `save:${tab.path}`;
    const epoch = nextEpoch(key);
    const generationAtStart = generation(tab.path);
    const sequenceAtStart = lastSequenceRef.current;
    const mutationId = api.createOperationId();
    const normalizedWriteVersion = await api.getTextVersion(tab.content);
    pendingOperationsRef.current.add(mutationId);
    pendingWriteVersionsRef.current.set(tab.path, normalizedWriteVersion);
    try {
      const snapshot = await api.writeFile(
        tab.path,
        tab.content,
        expectedVersionOverride === undefined ? tab.version : expectedVersionOverride,
        mutationId,
      );
      if (requestEpochRef.current[key] !== epoch) return false;
      if (
        generation(tab.path) !== generationAtStart
        && pathVersionsRef.current.get(tab.path) !== snapshot.version
      ) return false;
      const conflict = stateRef.current.openTabs.find((item) => item.id === id)?.conflict;
      if (
        conflict
        && conflict.detectedSequence > sequenceAtStart
        && pathVersionsRef.current.get(tab.path) !== snapshot.version
        && pathVersionsRef.current.get(tab.path) !== normalizedWriteVersion
      ) return false;
      const operation = snapshot.operation_id
        ? operationVersionsRef.current.get(snapshot.operation_id)
        : null;
      if (operation && (operation.path !== snapshot.path || operation.version !== snapshot.version)) {
        return false;
      }
      dispatch({ type: "APPLY_SNAPSHOT", id, snapshot });
      return true;
    } catch (error) {
      if (error instanceof AgentspaceApiError && error.status === 409) {
        try {
          const disk = await api.readFile(tab.path);
          const localVersion = await api.getTextVersion(tab.content);
          if (disk.version === localVersion) {
            dispatch({ type: "APPLY_SNAPSHOT", id, snapshot: disk });
            return true;
          }
          dispatch({
            type: "SET_CONFLICT",
            id,
            conflict: {
              kind: "modified",
              diskContent: disk.content,
              diskVersion: disk.version,
              detectedSequence: lastSequenceRef.current,
            },
          });
        } catch (readError) {
          if (readError instanceof AgentspaceApiError && readError.status === 404) {
            dispatch({
              type: "SET_CONFLICT",
              id,
              conflict: {
                kind: "deleted",
                diskContent: null,
                diskVersion: null,
                detectedSequence: lastSequenceRef.current,
              },
            });
          } else {
            setError(readError instanceof Error ? readError.message : "冲突内容读取失败", null);
          }
        }
        return false;
      }
      if (error instanceof AgentspaceApiError && error.status === 423 && error.detail.locks) {
        dispatch({ type: "SET_LOCKS", locks: error.detail.locks });
      }
      setError(
        error instanceof Error ? error.message : "文件保存失败",
        async () => { await saveFile(id, expectedVersionOverride); },
      );
      return false;
    } finally {
      pendingOperationsRef.current.delete(mutationId);
      if (pendingWriteVersionsRef.current.get(tab.path) === normalizedWriteVersion) {
        pendingWriteVersionsRef.current.delete(tab.path);
      }
    }
  }, [nextEpoch, setError]);

  const closeCleanTab = useCallback((id: string) => {
    const tab = stateRef.current.openTabs.find((item) => item.id === id);
    if (tab && !tab.isDirty) dispatch({ type: "CLOSE_TAB", id });
  }, []);

  const discardAndCloseTab = useCallback((id: string) => {
    dispatch({ type: "CLOSE_TAB", id });
  }, []);

  const setActiveTab = useCallback((id: string) => dispatch({ type: "SET_ACTIVE", id }), []);
  const updateContent = useCallback((id: string, content: string) => {
    dispatch({ type: "UPDATE_CONTENT", id, content });
  }, []);

  const createFile: UseAgentspaceResult["createFile"] = useCallback(async (parent: string, name: string) => {
    const path = joinPath(parent, name);
    try {
      await api.writeFile(path, "", null);
      await loadDirectory(parent, true);
      await openFile(path);
    } catch (error) {
      setError(error instanceof Error ? error.message : "文件创建失败", () => createFile(parent, name));
    }
  }, [loadDirectory, openFile, setError]);

  const createFolder: UseAgentspaceResult["createFolder"] = useCallback(async (parent: string, name: string) => {
    const path = joinPath(parent, name);
    try {
      await api.createDirectory(path);
      await loadDirectory(parent, true);
    } catch (error) {
      setError(error instanceof Error ? error.message : "文件夹创建失败", () => createFolder(parent, name));
    }
  }, [loadDirectory, setError]);

  const renamePath: UseAgentspaceResult["renamePath"] = useCallback(async (path: string, newName: string) => {
    try {
      const result = await api.renamePath(path, newName);
      dispatch({ type: "REWRITE_PATH", oldPath: result.old_path, newPath: result.new_path });
      await loadDirectory(parentPath(result.new_path), true);
    } catch (error) {
      setError(error instanceof Error ? error.message : "重命名失败", () => renamePath(path, newName));
    }
  }, [loadDirectory, setError]);

  const movePathToTrash: UseAgentspaceResult["movePathToTrash"] = useCallback(async (path: string) => {
    const dirty = stateRef.current.openTabs.some((tab) => isPathWithin(tab.path, path) && tab.isDirty);
    if (dirty) {
      setError("该路径仍有未保存标签，请先处理后再移入垃圾桶。", null);
      return;
    }
    try {
      await api.moveToTrash(path);
      dispatch({ type: "REMOVE_PATH", path });
      await Promise.all([loadDirectory(parentPath(path), true), loadTrashEntries()]);
    } catch (error) {
      setError(error instanceof Error ? error.message : "移入垃圾桶失败", () => movePathToTrash(path));
    }
  }, [loadDirectory, loadTrashEntries, setError]);

  const restoreTrashEntry: UseAgentspaceResult["restoreTrashEntry"] = useCallback(async (entryId: string) => {
    try {
      const result = await api.restoreTrash(entryId);
      await Promise.all([
        loadDirectory(parentPath(result.restored_path), true),
        loadTrashEntries(),
      ]);
    } catch (error) {
      setError(error instanceof Error ? error.message : "恢复失败", () => restoreTrashEntry(entryId));
    }
  }, [loadDirectory, loadTrashEntries, setError]);

  const purgeTrashEntry: UseAgentspaceResult["purgeTrashEntry"] = useCallback(async (entryId: string) => {
    try {
      await api.purgeTrash(entryId);
      await loadTrashEntries();
    } catch (error) {
      setError(error instanceof Error ? error.message : "永久删除失败", () => purgeTrashEntry(entryId));
    }
  }, [loadTrashEntries, setError]);

  const emptyTrash: UseAgentspaceResult["emptyTrash"] = useCallback(async () => {
    try {
      const result = await api.emptyTrash();
      await loadTrashEntries();
      if (result.failures.length) {
        setError(`有 ${result.failures.length} 个垃圾桶条目清理失败。`, emptyTrash);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "清空垃圾桶失败", emptyTrash);
    }
  }, [loadTrashEntries, setError]);

  const resolveConflictWithDisk = useCallback((tabId: string) => {
    dispatch({ type: "USE_DISK", id: tabId });
  }, []);

  const resolveConflictWithLocal = useCallback(async (tabId: string): Promise<boolean> => {
    const tab = stateRef.current.openTabs.find((item) => item.id === tabId);
    if (!tab?.conflict || tab.conflict.kind !== "modified") return false;
    return saveFile(tabId, tab.conflict.diskVersion);
  }, [saveFile]);

  const recreateDeletedConflict = useCallback(async (tabId: string): Promise<boolean> => {
    const tab = stateRef.current.openTabs.find((item) => item.id === tabId);
    if (!tab?.conflict || tab.conflict.kind !== "deleted") return false;
    return saveFile(tabId, null);
  }, [saveFile]);

  const discardDeletedConflict = useCallback((tabId: string) => {
    dispatch({ type: "DISCARD_DELETED", id: tabId });
  }, []);

  useEffect(() => {
    const handleEvent = (event: AgentspaceEvent) => {
      if (event.sequence > 0) {
        if (event.sequence <= lastSequenceRef.current) return;
        lastSequenceRef.current = event.sequence;
      }
      if (event.operation_id) {
        operationVersionsRef.current.set(event.operation_id, {
          path: event.new_path || event.path || "",
          version: event.version,
          sequence: event.sequence,
        });
      }
      if (event.path && event.kind !== "locks" && event.kind !== "resync") {
        pathVersionsRef.current.set(
          event.new_path || event.path,
          event.kind === "deleted" ? null : event.version,
        );
      }
      if (
        event.source === "watcher"
        && event.path
        && event.version
        && pendingWriteVersionsRef.current.get(event.path) === event.version
      ) {
        return;
      }
      if (
        event.source === "service"
        && event.operation_id
        && pendingOperationsRef.current.has(event.operation_id)
      ) {
        return;
      }
      if (event.kind === "watcher_error") {
        dispatch({ type: "SET_SYNC", state: "degraded" });
        setError(event.message || "外部文件实时同步不可用。", refreshExpandedDirectories);
        return;
      }
      if (event.kind === "locks") {
        dispatch({ type: "SET_LOCKS", locks: event.locks || [] });
        return;
      }
      if (event.kind === "trash_changed") {
        void loadTrashEntries();
        return;
      }
      if (event.kind === "resync") {
        globalGenerationRef.current += 1;
        for (const key of Object.keys(requestEpochRef.current)) nextEpoch(key);
        void refreshExpandedDirectories();
        void loadLocks();
        void loadTrashEntries();
        for (const tab of stateRef.current.openTabs) {
          const key = `file:${tab.path}`;
          const epoch = nextEpoch(key);
          const generationAtStart = generation(tab.path);
          const sequenceAtStart = lastSequenceRef.current;
          void api.readFile(tab.path).then((snapshot) => {
            if (
              requestEpochRef.current[key] !== epoch
              || generation(tab.path) !== generationAtStart
              || lastSequenceRef.current > sequenceAtStart
            ) return;
            const current = stateRef.current.openTabs.find((item) => item.id === tab.id);
            if (!current || snapshot.version === current.version) return;
            if (current.isDirty) {
              dispatch({
                type: "SET_CONFLICT",
                id: current.id,
                conflict: {
                  kind: "modified",
                  diskContent: snapshot.content,
                  diskVersion: snapshot.version,
                  detectedSequence: lastSequenceRef.current,
                },
              });
            } else {
              dispatch({ type: "APPLY_SNAPSHOT", id: current.id, snapshot });
            }
          }).catch((error) => {
            if (
              requestEpochRef.current[key] !== epoch
              || generation(tab.path) !== generationAtStart
              || lastSequenceRef.current > sequenceAtStart
            ) return;
            if (error instanceof AgentspaceApiError && error.status === 404) {
              if (tab.isDirty) {
                dispatch({
                  type: "SET_CONFLICT",
                  id: tab.id,
                  conflict: {
                    kind: "deleted",
                    diskContent: null,
                    diskVersion: null,
                    detectedSequence: lastSequenceRef.current,
                  },
                });
              } else {
                dispatch({ type: "CLOSE_TAB", id: tab.id });
              }
            }
          });
        }
        return;
      }

      bumpGeneration(event.path);
      bumpGeneration(event.new_path);
      if (event.kind === "moved" && event.path && event.new_path) {
        dispatch({ type: "REWRITE_PATH", oldPath: event.path, newPath: event.new_path });
        void loadDirectory(parentPath(event.path), true);
        void loadDirectory(parentPath(event.new_path), true);
        return;
      }
      if (!event.path) return;
      void loadDirectory(parentPath(event.path), true);
      const affected = stateRef.current.openTabs.filter((tab) =>
        event.is_directory ? isPathWithin(tab.path, event.path!) : tab.path === event.path,
      );
      if (event.kind === "deleted") {
        let closedCleanTab = false;
        for (const tab of affected) {
          if (tab.isDirty) {
            dispatch({
              type: "SET_CONFLICT",
              id: tab.id,
              conflict: {
                kind: "deleted",
                diskContent: null,
                diskVersion: null,
                detectedSequence: event.sequence,
              },
            });
          } else {
            dispatch({ type: "CLOSE_TAB", id: tab.id });
            closedCleanTab = true;
          }
        }
        if (closedCleanTab) {
          setError(`文件已被外部删除：${event.path}`, null);
        }
        return;
      }
      if (event.is_directory) return;
      for (const tab of affected) {
        const key = `file:${tab.path}`;
        const epoch = nextEpoch(key);
        const generationAtStart = generation(tab.path);
        const sequenceAtStart = lastSequenceRef.current;
        void api.readFile(tab.path).then((snapshot) => {
          if (
            requestEpochRef.current[key] !== epoch
            || generation(tab.path) !== generationAtStart
            || lastSequenceRef.current > sequenceAtStart
          ) return;
          const current = stateRef.current.openTabs.find((item) => item.id === tab.id);
          if (!current || snapshot.version === current.version) return;
          if (current.isDirty) {
            dispatch({
              type: "SET_CONFLICT",
              id: current.id,
              conflict: {
                kind: "modified",
                diskContent: snapshot.content,
                diskVersion: snapshot.version,
                detectedSequence: event.sequence,
              },
            });
          } else {
            dispatch({ type: "APPLY_SNAPSHOT", id: current.id, snapshot });
          }
        }).catch(() => undefined);
      }
    };

    return api.connectAgentspaceEvents(
      handleEvent,
      (syncState) => dispatch({ type: "SET_SYNC", state: syncState }),
    );
  }, [bumpGeneration, generation, loadDirectory, loadLocks, loadTrashEntries, nextEpoch, refreshExpandedDirectories, setError]);

  useEffect(() => {
    return () => {
      for (const key of Object.keys(requestEpochRef.current)) nextEpoch(key);
    };
  }, [nextEpoch]);

  const hasDirtyTabs = useMemo(
    () => state.openTabs.some((tab) => tab.isDirty),
    [state.openTabs],
  );

  return {
    directories: state.directories,
    expandedPaths: state.expandedPaths,
    selection: state.selection,
    openTabs: state.openTabs,
    activeTabId: state.activeTabId,
    locks: state.locks,
    trashEntries: state.trashEntries,
    trashExpanded: state.trashExpanded,
    syncState: state.syncState,
    error: state.error,
    hasDirtyTabs,
    loadDirectory,
    refreshExpandedDirectories,
    toggleDirectory,
    selectEntry,
    openFile,
    setActiveTab,
    updateContent,
    saveFile,
    closeCleanTab,
    discardAndCloseTab,
    createFile,
    createFolder,
    renamePath,
    movePathToTrash,
    setTrashExpanded: (expanded: boolean) => dispatch({ type: "SET_TRASH_EXPANDED", expanded }),
    restoreTrashEntry,
    purgeTrashEntry,
    emptyTrash,
    resolveConflictWithDisk,
    resolveConflictWithLocal,
    recreateDeletedConflict,
    discardDeletedConflict,
    clearError: () => dispatch({ type: "SET_ERROR", error: null }),
  };
}
