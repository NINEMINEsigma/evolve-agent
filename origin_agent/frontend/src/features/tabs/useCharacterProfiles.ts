import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentspaceEvent, CharacterProfileEntryDto, CharacterProfilesResponseDto } from "../../types";
import { fetchWithTimeout } from "../../services/fetchWithTimeout";
import { subscribeChatAgentspaceEvents } from "../../services/chatAgentspaceEventBus";
import { TIMING } from "../../constants/timing";

export interface UseCharacterProfilesState {
  profiles: CharacterProfileEntryDto[] | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/** 拉取角色档案目录并写入 state；请求失败写入 error，旧 profiles 保留。 */
async function fetchCharacterProfiles(
  commit: (payload: CharacterProfileEntryDto[] | null, error: string | null) => void,
): Promise<void> {
  try {
    const response = await fetchWithTimeout(
      "/api/characters/profiles",
      {},
      { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "character-profiles" },
    );
    if (!response.ok) {
      commit(null, `HTTP ${response.status}`);
      return;
    }
    const payload = (await response.json()) as CharacterProfilesResponseDto;
    commit(payload.characters ?? [], null);
  } catch (error) {
    commit(null, error instanceof Error ? error.message : String(error));
  }
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
 * 档案为全局数据，不依赖会话 ID；请求代际防止 Tab 快速切换期间旧响应覆盖。
 */
export function useCharacterProfiles(active: boolean): UseCharacterProfilesState {
  const [profiles, setProfiles] = useState<CharacterProfileEntryDto[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    await fetchCharacterProfiles((payload, errorMessage) => {
      if (generationRef.current !== generation) return;
      if (payload !== null) {
        setProfiles(payload);
        setError(null);
      } else {
        setError(errorMessage);
      }
    });
    if (generationRef.current === generation) {
      setLoading(false);
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

  return { profiles, loading, error, refresh };
}
