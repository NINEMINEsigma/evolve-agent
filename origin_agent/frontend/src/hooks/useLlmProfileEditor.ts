import { useCallback, useEffect, useRef, useState } from "react";
import type { LlmProfileManager } from "./useLlmProfiles";
import { LlmProfileMutationError } from "./useLlmProfiles";
import type { LlmProfile } from "../types";
import type { LlmEditorState, LlmProfileDraft, LlmProfileDraftValidation } from "../types/llmProfileUi";
import { EMPTY_LLM_PROFILE, LLM_PROFILE_FIELDS } from "../constants/llmProfile";
import { createLlmProfileDraft, generateDuplicateName, sameLlmProfile, validateLlmProfileDraft } from "../utils/llmProfile";

const viewState = (name = ""): LlmEditorState => ({
  kind: "view", selectedName: name, originalName: null, baseline: null, draft: null,
  busy: false, error: null, externalConflict: false, saveOutcome: "idle",
});
const isDirty = (state: LlmEditorState): boolean => {
  if (state.kind === "create") return true;
  if (!state.draft || !state.baseline) return false;
  const baseline = createLlmProfileDraft(state.baseline);
  return LLM_PROFILE_FIELDS.some((field) => state.draft?.[field] !== baseline[field]);
};
interface SubmittedEdit { originalName: string | null; profile: LlmProfile; baseline: LlmProfile | null }

export function useLlmProfileEditor(manager: LlmProfileManager) {
  const currentManager = useRef(manager);
  currentManager.current = manager;
  const [state, setState] = useState<LlmEditorState>(() => viewState());
  const stateRef = useRef(state);
  const [pendingLeave, setPendingLeave] = useState(false);
  const leaveAction = useRef<(() => void) | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [conflictOpen, setConflictOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const submitted = useRef<SubmittedEdit | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const publish = useCallback((next: LlmEditorState) => {
    stateRef.current = next;
    if (mounted.current) setState(next);
  }, []);
  const reset = useCallback((name: string) => {
    submitted.current = null;
    setConflictOpen(false);
    publish(viewState(name));
  }, [publish]);
  const requestLeave = useCallback((action: () => void) => {
    const current = stateRef.current;
    if (current.busy || leaveAction.current) return;
    if (isDirty(current) || current.saveOutcome === "uncertain") {
      leaveAction.current = action;
      setPendingLeave(true);
    } else { reset(current.selectedName); action(); }
  }, [reset]);
  const selectProfile = useCallback((name: string) => {
    requestLeave(() => reset(stateRef.current.selectedName === name ? "" : name));
  }, [requestLeave, reset]);
  const beginEdit = useCallback(() => {
    const current = stateRef.current;
    if (current.busy || current.kind !== "view") return;
    const profile = currentManager.current.profiles.find((item) => item.name === current.selectedName);
    if (!profile) return;
    setNotice(null);
    publish({ ...viewState(profile.name), kind: "edit", originalName: profile.name, baseline: { ...profile }, draft: createLlmProfileDraft(profile) });
  }, [publish]);
  const startCreate = useCallback((source: LlmProfile, duplicate: boolean) => {
    const profile = duplicate ? { ...source, name: generateDuplicateName(source.name, currentManager.current.profiles.map((item) => item.name)) }
      : { ...EMPTY_LLM_PROFILE, llm_client_name: source.llm_client_name, base_url: source.base_url };
    setNotice(null);
    submitted.current = null;
    publish({ ...viewState(), kind: "create", draft: createLlmProfileDraft(profile) });
  }, [publish]);
  const beginCreate = useCallback(() => {
    const source = currentManager.current.profiles.find((item) => item.name === stateRef.current.selectedName) ?? { ...EMPTY_LLM_PROFILE };
    requestLeave(() => startCreate(source, false));
  }, [requestLeave, startCreate]);
  const beginDuplicate = useCallback(() => {
    const source = currentManager.current.profiles.find((item) => item.name === stateRef.current.selectedName);
    if (source) requestLeave(() => startCreate(source, true));
  }, [requestLeave, startCreate]);
  const updateField = useCallback(<K extends keyof LlmProfileDraft>(field: K, value: LlmProfileDraft[K]) => {
    const current = stateRef.current;
    if (!current.draft || current.busy || current.saveOutcome === "uncertain") return;
    publish({ ...current, draft: { ...current.draft, [field]: value }, error: null });
  }, [publish]);
  const save = useCallback(async (): Promise<boolean> => {
    const current = stateRef.current;
    if (!current.draft || current.busy || current.externalConflict || current.saveOutcome === "uncertain") return false;
    const validation = validateLlmProfileDraft(current.draft, currentManager.current.profiles, current.originalName);
    if (!validation.profile) { publish({ ...current, error: "请修正标记的字段后再保存。" }); return false; }
    const payload = validation.profile;
    submitted.current = { originalName: current.originalName, profile: payload, baseline: current.baseline };
    publish({ ...current, busy: true, error: null, saveOutcome: "saving" });
    try {
      const saved = current.kind === "create" ? await currentManager.current.createProfile(payload)
        : await currentManager.current.updateProfile(current.originalName!, payload);
      reset(saved.name);
      setNotice("配置已保存。");
      return true;
    } catch (cause) {
      publish({ ...current, busy: false, error: cause instanceof Error ? cause.message : "保存失败",
        saveOutcome: cause instanceof LlmProfileMutationError && cause.uncertain ? "uncertain" : "idle" });
      return false;
    }
  }, [publish, reset]);
  const resolveLeave = useCallback(async (decision: "save" | "discard" | "cancel") => {
    if (stateRef.current.busy) return;
    if (decision === "cancel") { leaveAction.current = null; setPendingLeave(false); return; }
    if (decision === "save" && !await save()) return;
    const action = leaveAction.current;
    leaveAction.current = null;
    setPendingLeave(false);
    reset(stateRef.current.selectedName);
    action?.();
  }, [reset, save]);
  const cancel = useCallback(() => {
    requestLeave(() => reset(stateRef.current.originalName ?? stateRef.current.selectedName));
  }, [requestLeave, reset]);

  const requestDelete = useCallback(() => {
    if (stateRef.current.kind !== "view" || stateRef.current.busy || !stateRef.current.selectedName) return;
    publish({ ...stateRef.current, error: null });
    setDeleteTarget(stateRef.current.selectedName);
  }, [publish]);
  const cancelDelete = useCallback(() => { if (!stateRef.current.busy) setDeleteTarget(null); }, []);
  const confirmDelete = useCallback(async (replacementName: string | null): Promise<boolean> => {
    if (!deleteTarget || stateRef.current.busy) return false;
    publish({ ...stateRef.current, busy: true, error: null });
    try {
      const result = await currentManager.current.deleteProfile(deleteTarget, replacementName);
      reset("");
      setDeleteTarget(null);
      setNotice(result.pending_sessions?.length ? "配置已删除。正在处理的会话将保留本轮模型，后续使用替换配置。" : "配置已删除。");
      return true;
    } catch (cause) {
      publish({ ...stateRef.current, busy: false, error: cause instanceof Error ? cause.message : "删除失败" });
      return false;
    }
  }, [deleteTarget, publish, reset]);

  useEffect(() => {
    const current = stateRef.current;
    if (current.busy || current.saveOutcome === "uncertain" || manager.profilesStatus !== "ready") return;
    if (current.kind === "edit" && current.baseline && !current.externalConflict) {
      const latest = manager.profiles.find((item) => item.name === current.originalName);
      if (!latest || !sameLlmProfile(latest, current.baseline)) {
        publish({ ...current, externalConflict: true, error: "配置已在别处更新或删除，草稿已保留。" });
      }
    } else if (current.kind === "view" && current.selectedName && !manager.profiles.some((item) => item.name === current.selectedName)) {
      reset("");
    }
  }, [manager.profiles, manager.profilesStatus, state.busy, state.kind, publish, reset]);

  const reloadExternal = useCallback(() => {
    if (stateRef.current.busy) return;
    const name = stateRef.current.originalName ?? stateRef.current.selectedName;
    reset(currentManager.current.profiles.some((profile) => profile.name === name) ? name : "");
  }, [reset]);
  const saveAsNew = useCallback(() => {
    const current = stateRef.current;
    if (!current.draft || current.busy) return;
    submitted.current = null;
    setConflictOpen(false);
    publish({ ...viewState(), kind: "create", draft: { ...current.draft,
      name: generateDuplicateName(current.draft.name.trim() || "配置", currentManager.current.profiles.map((item) => item.name)) } });
  }, [publish]);
  const confirmSaveOutcome = useCallback(async () => {
    const operation = submitted.current;
    const current = stateRef.current;
    if (!operation || current.busy || current.saveOutcome !== "uncertain") return;
    publish({ ...current, busy: true });
    try {
      const list = await currentManager.current.refreshProfiles();
      const target = list.find((profile) => profile.name === operation.profile.name);
      if (target && sameLlmProfile(target, operation.profile)) {
        if (operation.originalName && operation.originalName !== target.name) {
          currentManager.current.handleProfileChanged({ operation: "renamed", old_name: operation.originalName, new_name: target.name });
        }
        reset(target.name);
        setNotice("已确认配置保存成功。");
        return;
      }
      const original = list.find((profile) => profile.name === operation.originalName);
      const notSaved = operation.originalName === null ? !target
        : !!original && !!operation.baseline && sameLlmProfile(original, operation.baseline)
          && (!target || target.name === operation.originalName);
      publish({ ...current, busy: false, saveOutcome: "idle", externalConflict: !notSaved,
        error: notSaved ? "尚未发现本次保存结果，可以检查后重新保存。" : "服务端配置与提交内容不同，草稿已保留，请处理冲突。" });
    } catch (cause) {
      publish({ ...current, busy: false, error: `确认失败：${cause instanceof Error ? cause.message : "请重试"}` });
    }
  }, [publish, reset]);
  const dirty = isDirty(state);
  useEffect(() => {
    if (!dirty && state.saveOutcome !== "uncertain") return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, state.saveOutcome]);
  const validation: LlmProfileDraftValidation = state.draft ? validateLlmProfileDraft(state.draft, manager.profiles, state.originalName)
    : { profile: null, errors: {} };
  return {
    state, dirty, validation, pendingLeave, deleteTarget, conflictOpen, notice,
    selectProfile, beginEdit, beginCreate, beginDuplicate, updateField, save, cancel,
    requestLeave, resolveLeave, requestDelete, confirmDelete, cancelDelete,
    reloadExternal, saveAsNew, confirmSaveOutcome,
    openConflict: () => setConflictOpen(true), closeConflict: () => setConflictOpen(false),
    dismissNotice: () => setNotice(null),
  };
}

export type LlmProfileEditorController = ReturnType<typeof useLlmProfileEditor>;
