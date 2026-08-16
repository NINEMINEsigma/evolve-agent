import { useCallback, useEffect, useMemo, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import { STORAGE_KEYS } from "../constants/storage";
import type { LlmProfile } from "../types";

export interface LlmServerDefaults {
  llm_model: string;
  llm_base_url: string;
  llm_temperature: number;
  llm_max_output_tokens: number;
  llm_reasoning_effort: string;
  llm_client_name: string;
  llm_max_context_tokens: number;
}

const DEFAULT_PROFILE_NAME = "default";

function buildDefaultProfile(defaults: LlmServerDefaults): LlmProfile {
  return {
    name: DEFAULT_PROFILE_NAME,
    llm_client_name: defaults.llm_client_name || "openai_client",
    base_url: defaults.llm_base_url || "",
    model: defaults.llm_model || "",
    api_key: "",
    temperature: defaults.llm_temperature ?? 0.7,
    max_output_tokens: defaults.llm_max_output_tokens ?? 4096,
    reasoning_effort: defaults.llm_reasoning_effort || "",
    max_context_tokens: defaults.llm_max_context_tokens ?? 128000,
  };
}

export function useLlmProfiles(serverDefaults: LlmServerDefaults) {
  const [customProfiles, setCustomProfiles] = usePersistentState<LlmProfile[]>(
    STORAGE_KEYS.LLM_PROFILES,
    [],
  );
  const [activeProfileName, setActiveProfileName] = usePersistentState<string>(
    STORAGE_KEYS.ACTIVE_LLM_PROFILE,
    DEFAULT_PROFILE_NAME,
  );
  const [availableClients, setAvailableClients] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/llm/clients")
      .then((r) => r.json())
      .then((data) => setAvailableClients(data.clients || []))
      .catch(() => setAvailableClients([]));
  }, []);

  const defaultProfile = useMemo(
    () => buildDefaultProfile(serverDefaults),
    [serverDefaults],
  );

  const profiles = useMemo(
    () => [defaultProfile, ...customProfiles],
    [defaultProfile, customProfiles],
  );

  const activeProfile = useMemo(() => {
    const found = profiles.find((p) => p.name === activeProfileName);
    return found || defaultProfile;
  }, [profiles, activeProfileName, defaultProfile]);

  const setActiveProfile = useCallback(
    (name: string) => setActiveProfileName(name),
    [setActiveProfileName],
  );

  const addProfile = useCallback(
    (profile: LlmProfile) => {
      setCustomProfiles((prev) => [...prev, profile]);
    },
    [setCustomProfiles],
  );

  const updateProfile = useCallback(
    (name: string, profile: LlmProfile) => {
      setCustomProfiles((prev) =>
        prev.map((p) => (p.name === name ? profile : p)),
      );
    },
    [setCustomProfiles],
  );

  const deleteProfile = useCallback(
    (name: string) => {
      setCustomProfiles((prev) => prev.filter((p) => p.name !== name));
      if (activeProfileName === name) {
        setActiveProfileName(DEFAULT_PROFILE_NAME);
      }
    },
    [setCustomProfiles, activeProfileName, setActiveProfileName],
  );

  const toProfilePayload = useCallback((): Record<string, unknown> | null => {
    if (activeProfileName === DEFAULT_PROFILE_NAME) return null;
    const { name: _, ...payload } = activeProfile;
    return payload;
  }, [activeProfileName, activeProfile]);

  return {
    profiles,
    activeProfileName,
    activeProfile,
    setActiveProfile,
    addProfile,
    updateProfile,
    deleteProfile,
    toProfilePayload,
    availableClients,
  };
}

export type LlmProfileManager = ReturnType<typeof useLlmProfiles>;