import { useEffect, useRef } from "react";
import type { AgentspaceEvent, CharacterAvatarsResponseDto } from "../../types";
import { fetchWithTimeout } from "../../services/fetchWithTimeout";
import { subscribeChatAgentspaceEvents } from "../../services/chatAgentspaceEventBus";
import { TIMING } from "../../constants/timing";
import { useCharacterAvatarStore } from "./characterAvatarStore";

/** 拉取头像映射并写入 store；失败静默保留旧映射（下次事件/重连重试）。 */
async function refreshAvatarEntries(): Promise<void> {
  try {
    const response = await fetchWithTimeout(
      "/api/characters/avatars",
      {},
      { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "character-avatars" },
    );
    if (!response.ok) return;
    const payload = (await response.json()) as CharacterAvatarsResponseDto;
    useCharacterAvatarStore.getState().setAvatars(payload);
  } catch {
    // 静默失败：不弹通知，事件/重连 resync 时重试。
  }
}

/** 判定事件是否可能影响头像映射（事件 path 为 agentspace 相对路径）。 */
function avatarRelevantEvent(event: AgentspaceEvent): boolean {
  if (event.kind === "resync") return true;
  const candidates = [event.path, event.new_path];
  for (const p of candidates) {
    if (!p) continue;
    if (p === "SOUL.md.meta") return true;
    if (p === "characters/" || p.startsWith("characters/")) return true;
  }
  return false;
}

/** 挂载拉取一次 + 订阅聊天页 Agentspace 事件，命中后去抖重拉。 */
export function useCharacterAvatarSync(): void {
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    void refreshAvatarEntries();
    const handle = (event: AgentspaceEvent) => {
      if (!avatarRelevantEvent(event)) return;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void refreshAvatarEntries();
      }, TIMING.CHARACTER_AVATAR_REFRESH_DEBOUNCE);
    };
    const unsubscribe = subscribeChatAgentspaceEvents(handle);
    return () => {
      unsubscribe();
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);
}
