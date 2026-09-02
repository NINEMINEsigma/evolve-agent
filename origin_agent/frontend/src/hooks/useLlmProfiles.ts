import { useCallback, useEffect, useMemo, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import { STORAGE_KEYS } from "../constants/storage";
import type { LlmProfile } from "../types";

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
  };
}

export type LlmProfileManager = ReturnType<typeof useLlmProfiles>;
