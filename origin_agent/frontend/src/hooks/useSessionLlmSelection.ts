import { useCallback, useEffect, useRef, useState } from "react";
import type { LlmLoadStatus, LlmProfile, LlmProfileChangeEvent, SessionLlmSelectionStatus } from "../types";
import { STORAGE_KEYS } from "../constants/storage";
import {
  fetchSessionLlmProfile, readSessionLlmSelection, removeSessionLlmSelection,
  replaceStoredSessionLlmSelections, sessionLlmSelectionKey, writeSessionLlmSelection,
} from "../services/sessionLlmSelection";

interface SessionLlmSelectionOptions {
  sessionId: string;
  profiles: LlmProfile[];
  profilesStatus: LlmLoadStatus;
}
interface SelectionState {
  sessionId: string;
  name: string;
  status: SessionLlmSelectionStatus;
  error: string | null;
}

export function useSessionLlmSelection(options: SessionLlmSelectionOptions) {
  const latest = useRef(options);
  latest.current = options;
  const memory = useRef(new Map<string, string>());
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const [state, setState] = useState<SelectionState>({ sessionId: "", name: "", status: "idle", error: null });
  const stateRef = useRef(state);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const publish = useCallback((next: SelectionState) => {
    stateRef.current = next;
    setState(next);
  }, []);
  const invalidate = useCallback(() => {
    generation.current++;
    request.current?.abort();
    request.current = null;
  }, []);

  const refreshSessionSelection = useCallback(async (): Promise<void> => {
    invalidate();
    const { sessionId, profiles, profilesStatus } = latest.current;
    const token = generation.current;
    if (!sessionId) {
      publish({ sessionId, name: "", status: "idle", error: null });
      return;
    }
    if (profilesStatus !== "ready") return;
    const validName = (name: string) => name === "" || profiles.some((profile) => profile.name === name);
    const local = memory.current.get(sessionId) ?? readSessionLlmSelection(sessionId);
    if (local !== undefined && validName(local)) {
      memory.current.set(sessionId, local);
      publish({ sessionId, name: local, status: "ready", error: null });
      return;
    }
    if (local !== undefined) {
      memory.current.delete(sessionId);
      removeSessionLlmSelection(sessionId);
      setStorageWarning("原待用配置已失效，正在从该会话保存的配置恢复；也可重新选择模型。");
    }
    publish({ sessionId, name: "", status: "loading", error: null });
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await fetchSessionLlmProfile(sessionId, controller.signal);
      if (token !== generation.current || latest.current.sessionId !== sessionId) return;
      const name = result.profile_name ?? "";
      const exists = !name || (result.available && latest.current.profiles.some((profile) => profile.name === name));
      publish({ sessionId, name, status: exists ? "ready" : "error", error: exists ? null : "配置已失效，请重新选择模型。" });
    } catch (cause) {
      if (controller.signal.aborted || token !== generation.current || latest.current.sessionId !== sessionId) return;
      publish({ sessionId, name: "", status: "error", error: cause instanceof Error ? cause.message : "读取会话模型失败" });
    } finally {
      if (request.current === controller) request.current = null;
    }
  }, [invalidate, publish]);

  useEffect(() => {
    void refreshSessionSelection();
    return invalidate;
  }, [options.sessionId, options.profiles, options.profilesStatus, refreshSessionSelection, invalidate]);

  const setActiveProfile = useCallback((name: string) => {
    const { sessionId, profiles, profilesStatus } = latest.current;
    if (!sessionId || profilesStatus !== "ready" || (name && !profiles.some((profile) => profile.name === name))) return;
    invalidate();
    memory.current.set(sessionId, name);
    // 同步更新 ref，快速点击发送不必等待 React effect。
    publish({ sessionId, name, status: "ready", error: null });
    setStorageWarning(writeSessionLlmSelection(sessionId, name) ? null : "浏览器无法保存选择；本次页面内仍然有效，刷新后请重新选择。");
  }, [invalidate, publish]);

  const toProfileName = useCallback((sessionId: string): string | null => {
    const current = stateRef.current;
    const config = latest.current;
    if (!sessionId || config.sessionId !== sessionId || current.sessionId !== sessionId
      || current.status !== "ready" || config.profilesStatus !== "ready") return null;
    if (current.name && !config.profiles.some((profile) => profile.name === current.name)) return null;
    return current.name;
  }, []);

  const handleProfileNameChange = useCallback((event: LlmProfileChangeEvent) => {
    if (!event.old_name) return;
    invalidate();
    const target = event.new_name ?? "";
    replaceStoredSessionLlmSelections(event.old_name, target);
    memory.current.forEach((name, sid) => {
      if (name === event.old_name) memory.current.set(sid, target);
    });
    const current = stateRef.current;
    if (current.name === event.old_name) publish({ ...current, name: target, status: "loading", error: null });
  }, [invalidate, publish]);

  const forgetSessionSelection = useCallback((sessionId: string) => {
    memory.current.delete(sessionId);
    removeSessionLlmSelection(sessionId);
    if (latest.current.sessionId === sessionId) {
      invalidate();
      publish({ sessionId, name: "", status: "idle", error: null });
    }
  }, [invalidate, publish]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      const sid = latest.current.sessionId;
      if (event.key === null) memory.current.clear();
      else {
        if (!event.key.startsWith(STORAGE_KEYS.SESSION_LLM_PROFILE_PREFIX)) return;
        try { memory.current.delete(decodeURIComponent(event.key.slice(STORAGE_KEYS.SESSION_LLM_PROFILE_PREFIX.length))); }
        catch { return; }
      }
      if (!sid || (event.key !== null && event.key !== sessionLlmSelectionKey(sid))) return;
      void refreshSessionSelection();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [refreshSessionSelection]);

  const current = state.sessionId === options.sessionId;
  const selectionStatus: SessionLlmSelectionStatus = !options.sessionId ? "idle"
    : options.profilesStatus !== "ready" ? options.profilesStatus
      : current ? state.status : "loading";
  return {
    sessionId: options.sessionId,
    activeProfileName: current ? state.name : "",
    selectionStatus,
    selectionError: current ? state.error : null,
    storageWarning,
    setActiveProfile, toProfileName, refreshSessionSelection, handleProfileNameChange, forgetSessionSelection,
  };
}

export type SessionLlmSelectionManager = ReturnType<typeof useSessionLlmSelection>;
