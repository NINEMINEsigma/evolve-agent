import { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentLoopSettingsHttpError, readAgentLoopSettings, updateAgentLoopSettings,
} from "./api";
import { agentLoopSettingsLabels as labels } from "./labels";
import type {
  AgentLoopSettingsReadStatus, AgentLoopSettingsRefreshOptions, AgentLoopSettingsSaveOutcome,
  AgentLoopSettingsState, UseAgentLoopSettingsState,
} from "./types";

interface EditorState {
  state: AgentLoopSettingsState | null;
  draft: string;
  baselineText: string;
  baselineValue: number | null;
  readStatus: AgentLoopSettingsReadStatus;
  saveOutcome: AgentLoopSettingsSaveOutcome;
  error: string | null;
  notice: string | null;
  validationError: string | null;
}

interface SettingsRequest {
  generation: number;
  kind: "read" | "write";
  controller: AbortController;
}

function dirty(editor: EditorState): boolean {
  return editor.draft.trim() !== editor.baselineText;
}

function adopt(editor: EditorState, state: AgentLoopSettingsState): EditorState {
  const draft = String(state.effective_max_tool_turns);
  return { ...editor, state, draft, baselineText: draft, baselineValue: state.max_tool_turns };
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : labels.requestError;
}

export function useAgentLoopSettings(active: boolean): UseAgentLoopSettingsState {
  const [editor, setEditor] = useState<EditorState>({
    state: null, draft: "", baselineText: "", baselineValue: null,
    readStatus: "idle", saveOutcome: "idle", error: null, notice: null, validationError: null,
  });
  const editorRef = useRef(editor);
  const mountedRef = useRef(false);
  const activeRef = useRef(active);
  activeRef.current = active;
  const generationRef = useRef(0);
  const requestRef = useRef<SettingsRequest | null>(null);
  const pendingActivationRefresh = useRef(false);

  const publish = useCallback((next: EditorState) => {
    editorRef.current = next;
    if (mountedRef.current) setEditor(next);
  }, []);

  const owns = useCallback((request: SettingsRequest): boolean => (
    mountedRef.current && requestRef.current === request
    && generationRef.current === request.generation
  ), []);

  const refresh = useCallback(async (
    options: AgentLoopSettingsRefreshOptions = {},
  ): Promise<boolean> => {
    if (!mountedRef.current || requestRef.current !== null) return false;
    const request: SettingsRequest = {
      generation: ++generationRef.current, kind: "read", controller: new AbortController(),
    };
    requestRef.current = request;
    publish({ ...editorRef.current, readStatus: "loading", error: null, notice: null });
    try {
      const state = await readAgentLoopSettings(request.controller.signal);
      if (!owns(request)) return false;
      const previous = editorRef.current;
      const next = options.discardDraft || !previous.state || !dirty(previous)
        ? adopt(previous, state) : { ...previous, state };
      publish({
        ...next, readStatus: "ready", saveOutcome: "idle", error: null,
        validationError: options.discardDraft || !dirty(previous) ? null : previous.validationError,
        notice: previous.saveOutcome === "uncertain" ? labels.rereadNotice : null,
      });
      return true;
    } catch (cause) {
      if (!owns(request)) return false;
      publish({ ...editorRef.current, readStatus: "error", error: message(cause) });
      return false;
    } finally {
      if (owns(request)) requestRef.current = null;
    }
  }, [owns, publish]);

  const write = useCallback(async (value: number | null): Promise<boolean> => {
    const current = editorRef.current;
    if (!mountedRef.current || requestRef.current !== null || current.readStatus !== "ready"
      || current.saveOutcome !== "idle" || !current.state) return false;
    const request: SettingsRequest = {
      generation: ++generationRef.current, kind: "write", controller: new AbortController(),
    };
    requestRef.current = request;
    publish({ ...current, saveOutcome: "saving", error: null, notice: null, validationError: null });
    try {
      const state = await updateAgentLoopSettings(value, request.controller.signal);
      if (!owns(request)) return false;
      publish({
        ...adopt(editorRef.current, state), readStatus: "ready", saveOutcome: "idle",
        error: null, notice: labels.saved, validationError: null,
      });
      return true;
    } catch (cause) {
      if (!owns(request)) return false;
      const uncertain = !(cause instanceof AgentLoopSettingsHttpError) || cause.uncertain;
      publish({
        ...editorRef.current, saveOutcome: uncertain ? "uncertain" : "idle",
        error: message(cause), notice: null,
      });
      return false;
    } finally {
      if (owns(request)) {
        requestRef.current = null;
        const shouldRefresh = pendingActivationRefresh.current && activeRef.current
          && editorRef.current.saveOutcome !== "uncertain";
        pendingActivationRefresh.current = false;
        if (shouldRefresh) void refresh();
      }
    }
  }, [owns, publish, refresh]);

  const setDraft = useCallback((value: string): void => {
    const current = editorRef.current;
    if (requestRef.current !== null || current.readStatus !== "ready"
      || current.saveOutcome !== "idle" || !current.state) return;
    publish({ ...current, draft: value, validationError: null, notice: null });
  }, [publish]);

  const save = useCallback(async (): Promise<boolean> => {
    const current = editorRef.current;
    if (requestRef.current !== null || current.readStatus !== "ready"
      || current.saveOutcome !== "idle" || !current.state) return false;
    const text = current.draft.trim();
    const value = text === "" ? null : Number(text);
    if (text !== "" && (!/^[0-9]+$/.test(text) || value === null
      || !Number.isSafeInteger(value) || value < 1)) {
      publish({ ...current, validationError: labels.validationError });
      return false;
    }
    return write(value);
  }, [publish, write]);

  const restoreDefault = useCallback((): Promise<boolean> => write(null), [write]);

  useEffect(() => {
    mountedRef.current = true;
    // StrictMode重放时，用已清理的ref恢复显示，不继承旧请求的在途状态。
    publish(editorRef.current);
    return () => {
      mountedRef.current = false;
      generationRef.current++;
      const request = requestRef.current;
      requestRef.current = null;
      pendingActivationRefresh.current = false;
      request?.controller.abort();
      const current = editorRef.current;
      editorRef.current = {
        ...current,
        readStatus: current.readStatus === "loading" ? (current.state ? "ready" : "idle") : current.readStatus,
        saveOutcome: request?.kind === "write" ? "uncertain" : current.saveOutcome,
        error: request?.kind === "write" ? labels.unknownSave : current.error,
      };
    };
  }, [publish]);

  useEffect(() => {
    if (!active) {
      pendingActivationRefresh.current = false;
      return;
    }
    if (editorRef.current.saveOutcome === "uncertain") return;
    if (requestRef.current?.kind === "write") {
      pendingActivationRefresh.current = true;
      return;
    }
    if (requestRef.current === null) void refresh();
  }, [active, refresh]);

  const isDirty = dirty(editor);
  const busy = editor.saveOutcome === "saving";
  return {
    state: editor.state, draft: editor.draft, readStatus: editor.readStatus,
    saveOutcome: editor.saveOutcome, loading: editor.readStatus === "loading", busy,
    dirty: isDirty, error: editor.error, notice: editor.notice,
    validationError: editor.validationError,
    externalChange: isDirty && editor.state !== null
      && editor.state.max_tool_turns !== editor.baselineValue,
    shouldBlockUnload: isDirty || busy || editor.saveOutcome === "uncertain",
    setDraft, refresh, save, restoreDefault,
  };
}
