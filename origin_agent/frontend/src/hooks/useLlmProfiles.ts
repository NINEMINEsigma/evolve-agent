import { useCallback, useEffect, useMemo, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import { STORAGE_KEYS } from "../constants/storage";
import type { LlmProfile, ApprovalProfileState } from "../types";

async function responseError(response: Response): Promise<Error> {
  const data = await response.json().catch(() => ({}));
  return new Error(data.detail || `请求失败 (${response.status})`);
}

export function useLlmProfiles() {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeProfileName, setActiveProfileName] = usePersistentState<string>(
    STORAGE_KEYS.ACTIVE_LLM_PROFILE,
    "",
  );
  const [availableClients, setAvailableClients] = useState<string[]>([]);
  const [approvalProfileState, setApprovalProfileState] = useState<ApprovalProfileState>({ profile_name: null, model: null, available: false });

  const fetchProfiles = useCallback(async (): Promise<LlmProfile[]> => {
    const response = await fetch("/api/llm/profiles");
    if (!response.ok) throw await responseError(response);
    const data = await response.json();
    if (!Array.isArray(data.profiles)) {
      throw new Error("服务端返回的 Profile 列表格式无效");
    }
    return data.profiles as LlmProfile[];
  }, []);

  const refreshProfiles = useCallback(async (): Promise<LlmProfile[]> => {
    try {
      const next = await fetchProfiles();
      setProfiles(next);
      setError(null);
      return next;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, [fetchProfiles]);

  useEffect(() => {
    fetch("/api/llm/clients")
      .then(async (response) => {
        if (!response.ok) throw await responseError(response);
        return response.json();
      })
      .then((data) => setAvailableClients(data.clients || []))
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));

    void refreshProfiles().catch(() => {});
    void fetchApprovalProfile().catch(() => {});
  }, [refreshProfiles]);

  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.name === activeProfileName) || null,
    [profiles, activeProfileName],
  );

  const setActiveProfile = useCallback(
    (name: string) => setActiveProfileName(name),
    [setActiveProfileName],
  );

  const createProfile = useCallback(async (profile: LlmProfile): Promise<LlmProfile> => {
    try {
      const response = await fetch("/api/llm/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      await refreshProfiles();
      setError(null);
      return data.profile as LlmProfile;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, [refreshProfiles]);

  const updateProfile = useCallback(async (
    originalName: string,
    profile: LlmProfile,
  ): Promise<LlmProfile> => {
    try {
      const response = await fetch("/api/llm/profiles", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: originalName, profile }),
      });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      if (activeProfileName === originalName && profile.name !== originalName) {
        setActiveProfileName(profile.name);
      }
      await refreshProfiles();
      setError(null);
      return data.profile as LlmProfile;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, [activeProfileName, refreshProfiles, setActiveProfileName]);

  const deleteProfile = useCallback(async (
    profileName: string,
    replacementProfileName: string | null,
  ): Promise<void> => {
    const previousActiveName = activeProfileName;
    if (previousActiveName === profileName) {
      setActiveProfileName(replacementProfileName ?? "");
    }
    try {
      const response = await fetch("/api/llm/profiles", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_name: profileName,
          replacement_profile_name: replacementProfileName,
        }),
      });
      if (!response.ok) throw await responseError(response);
      await refreshProfiles();
      setError(null);
    } catch (cause) {
      if (previousActiveName === profileName) {
        setActiveProfileName(previousActiveName);
      }
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, [activeProfileName, refreshProfiles, setActiveProfileName]);

  const fetchApprovalProfile = useCallback(async (): Promise<ApprovalProfileState> => {
    try {
      const response = await fetch("/api/approval/profile");
      if (!response.ok) throw await responseError(response);
      const data = await response.json() as ApprovalProfileState;
      setApprovalProfileState(data);
      return data;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      return { profile_name: null, model: null, available: false };
    }
  }, []);

  const setApprovalProfile = useCallback(async (profileName: string | null): Promise<ApprovalProfileState> => {
    try {
      const response = await fetch("/api/approval/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: profileName }),
      });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      const state = data.state as ApprovalProfileState;
      setApprovalProfileState(state);
      setError(null);
      return state;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      throw cause;
    }
  }, []);

  const handleApprovalProfileChanged = useCallback((msg: {
    approval_profile_name?: string | null;
    approval_profile_model?: string | null;
    approval_profile_available?: boolean;
    handsfree_mode?: boolean | null;
  }) => {
    setApprovalProfileState({
      profile_name: msg.approval_profile_name ?? null,
      model: msg.approval_profile_model ?? null,
      available: msg.approval_profile_available ?? false,
    });
  }, []);

  const approvalProfileName = approvalProfileState.profile_name;
  const approvalProfile = useMemo(
    () => profiles.find((p) => p.name === approvalProfileName) || null,
    [profiles, approvalProfileName],
  );

  const handleProfileChanged = useCallback((event: {
    old_name?: string | null;
    new_name?: string | null;
  }) => {
    if (event.old_name && activeProfileName === event.old_name) {
      setActiveProfileName(event.new_name ?? "");
    }
    void refreshProfiles().catch(() => {});
  }, [activeProfileName, refreshProfiles, setActiveProfileName]);

  const toProfileName = useCallback((): string => activeProfileName, [activeProfileName]);

  return {
    profiles,
    activeProfileName,
    activeProfile,
    setActiveProfile,
    createProfile,
    updateProfile,
    deleteProfile,
    refreshProfiles,
    handleProfileChanged,
    toProfileName,
    availableClients,
    error,
    approvalProfileState,
    approvalProfileName,
    approvalProfile,
    fetchApprovalProfile,
    setApprovalProfile,
    handleApprovalProfileChanged,
  };
}

export type LlmProfileManager = ReturnType<typeof useLlmProfiles>;
