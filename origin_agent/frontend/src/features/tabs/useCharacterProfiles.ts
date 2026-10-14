import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentspaceEvent, CharacterProfileEntryDto } from "../../types";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";
import { subscribeChatAgentspaceEvents } from "../../services/chatAgentspaceEventBus";
import { TIMING } from "../../constants/timing";

export interface UseCharacterProfilesState {
  profiles: CharacterProfileEntryDto[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/** 严格校验响应形状：characters 缺失或非数组按错误处理，不成功返回 []。 */
function decodeCharacterProfiles(payload: unknown): CharacterProfileEntryDto[] {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Invalid character profiles response");
  }
  const characters = (payload as Record<string, unknown>).characters;
  if (!Array.isArray(characters)) throw new Error("Character profiles payload is not an array");
  for (const entry of characters) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("Invalid character profile entry");
    }
    const item = entry as Record<string, unknown>;
    if (typeof item.name !== "string" || (item.character_type !== "roleplay" && item.character_type !== "task")) {
      throw new Error("Invalid character profile identity");
    }
    if (typeof item.profile_available !== "boolean") throw new Error("Invalid character profile availability");
    if (item.error !== null && typeof item.error !== "string") throw new Error("Invalid character profile error");
  }
  return characters as CharacterProfileEntryDto[];
}

/** 判定事件是否可能影响角色档案（事件 path 为 agentspace 相对路径）。 */
function profileRelevantEvent(event: AgentspaceEvent): boolean {
  if (event.kind === "resync") return true;
  const candidates = [event.path, event.new_path];
  for (const p of candidates) {
    if (!p) continue;
    if (p === "characters/" || p.startsWith("characters/")) return true;
  }
  return false;
}

/**
 * 角色档案数据 hook：激活时重拉，激活期间订阅 Agentspace 事件去抖刷新。
 * 档案为全局数据，不依赖会话 ID；读取带完整 JSON 截止与卸载取消，代际防止
 * Tab 快速切换期间旧响应覆盖。
 */
export function useCharacterProfiles(active: boolean): UseCharacterProfilesState {
  const [profiles, setProfiles] = useState<CharacterProfileEntryDto[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const result = await fetchJsonWithTimeout(
        "/api/characters/profiles", { signal: controller.signal },
        { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "character-profiles" },
        decodeCharacterProfiles,
      );
      if (generationRef.current !== generation) return;
      setProfiles(result);
      setError(null);
    } catch (failure) {
      if (generationRef.current !== generation) return;
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (generationRef.current === generation) {
        setLoading(false);
        requestRef.current = null;
      }
    }
  }, []);

  // Fetch every time the tab becomes active (activation implies re-fetch).
  useEffect(() => {
    if (active) void refresh();
  }, [active, refresh]);

  // While active, subscribe to agentspace events and debounce-refresh on
  // characters/ changes or resync; unsubscribe and clear the timer on exit.
  useEffect(() => {
    if (!active) return;
    let timer: number | null = null;
    const handle = (event: AgentspaceEvent) => {
      if (!profileRelevantEvent(event)) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        void refresh();
      }, TIMING.CHARACTER_PROFILES_REFRESH_DEBOUNCE);
    };
    const unsubscribe = subscribeChatAgentspaceEvents(handle);
    return () => {
      unsubscribe();
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };
  }, [active, refresh]);

  // 卸载时取消在途读取。
  useEffect(() => () => {
    generationRef.current++;
    requestRef.current?.abort();
    requestRef.current = null;
  }, []);

  return { profiles, loading, error, refresh };
}