import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePersistentState } from "./usePersistentState";
import { STORAGE_KEYS } from "../constants/storage";
import type { LlmProfile } from "../types";

export function useLlmProfiles() {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeProfileName, setActiveProfileName] = usePersistentState<string>(
    STORAGE_KEYS.ACTIVE_LLM_PROFILE,
    "",
  );
  const [availableClients, setAvailableClients] = useState<string[]>([]);
  const initializedRef = useRef(false);

  // ── fetch profiles from server ──
  const fetchProfiles = useCallback(async (): Promise<LlmProfile[]> => {
    const r = await fetch("/api/llm/profiles");
    const data = await r.json();
    return (data.profiles || []) as LlmProfile[];
  }, []);

  // ── PUT profiles to server (atomic replace) ──
  // 成功时返回后端保存后的完整 profiles（带新生成的 uid），失败时返回 null
  const putProfiles = useCallback(async (next: LlmProfile[]): Promise<LlmProfile[] | null> => {
    try {
      const r = await fetch("/api/llm/profiles", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profiles: next }),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        setError(data.detail || `保存失败 (${r.status})`);
        return null;
      }
      const data = await r.json();
      setError(null);
      // 后端返回保存后的 profiles（含新生成的 uid），供调用方更新本地 state
      return (data.profiles || []) as LlmProfile[];
    } catch (e) {
      setError(`网络错误: ${e}`);
      return null;
    }
  }, []);

  // ── mount: fetch + one-time legacy localStorage migration ──
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    (async () => {
      // Fetch available clients
      fetch("/api/llm/clients")
        .then((r) => r.json())
        .then((data) => setAvailableClients(data.clients || []))
        .catch(() => setAvailableClients([]));

      const serverProfiles = await fetchProfiles();

      // One-time migration: read legacy localStorage profiles
      let legacy: LlmProfile[] = [];
      try {
        const raw = localStorage.getItem(STORAGE_KEYS.LLM_PROFILES);
        if (raw) {
          legacy = JSON.parse(raw) as LlmProfile[];
          if (!Array.isArray(legacy)) legacy = [];
        }
      } catch { legacy = []; }

      if (legacy.length > 0) {
        // Merge: server-first, add legacy entries whose name doesn't exist on server
        const serverNames = new Set(serverProfiles.map((p) => p.name));
        const merged = [...serverProfiles];
        for (const p of legacy) {
          if (!serverNames.has(p.name)) merged.push(p);
        }
        const saved = await putProfiles(merged);
        if (saved) {
          setProfiles(saved);
          localStorage.removeItem(STORAGE_KEYS.LLM_PROFILES);
        } else {
          // PUT failed — keep server profiles, leave legacy in localStorage
          setProfiles(serverProfiles);
        }
      } else {
        setProfiles(serverProfiles);
      }
    })();
  }, [fetchProfiles, putProfiles]);

  const activeProfile = useMemo(() => {
    const found = profiles.find((p) => p.name === activeProfileName);
    return found || profiles[0] || null;
  }, [profiles, activeProfileName]);

  const setActiveProfile = useCallback(
    (name: string) => setActiveProfileName(name),
    [setActiveProfileName],
  );

  // ── mutations: optimistic update → PUT → replace with server response (含 uid) ──
  const addProfile = useCallback(
    (profile: LlmProfile) => {
      const next = [...profiles, profile];
      setProfiles(next);
      putProfiles(next).then((saved) => {
        if (saved) setProfiles(saved);
        else setProfiles(profiles); // rollback
      });
    },
    [profiles, putProfiles],
  );

  const updateProfile = useCallback(
    (name: string, profile: LlmProfile) => {
      const next = profiles.map((p) => (p.name === name ? profile : p));
      setProfiles(next);
      putProfiles(next).then((saved) => {
        if (saved) setProfiles(saved);
        else setProfiles(profiles); // rollback
      });
    },
    [profiles, putProfiles],
  );

  const deleteProfile = useCallback(
    (name: string) => {
      const next = profiles.filter((p) => p.name !== name);
      setProfiles(next);
      if (activeProfileName === name) {
        setActiveProfileName(next[0]?.name ?? "");
      }
      putProfiles(next).then((saved) => {
        if (saved) setProfiles(saved);
        else setProfiles(profiles); // rollback
      });
    },
    [profiles, activeProfileName, setActiveProfileName, putProfiles],
  );

  const toProfilePayload = useCallback((): Record<string, unknown> | null => {
    if (!activeProfile) return null;
    const { name: _, ...payload } = activeProfile;
    return payload;
  }, [activeProfile]);

  return {
    profiles,
    activeProfileName: activeProfile?.name ?? "",
    activeProfile,
    setActiveProfile,
    addProfile,
    updateProfile,
    deleteProfile,
    toProfilePayload,
    availableClients,
    error,
  };
}

export type LlmProfileManager = ReturnType<typeof useLlmProfiles>;