import { create } from "zustand";
import type { CharacterAvatarsResponseDto } from "../../types";

/** 角色名 → 头像 URL；null 表示该角色已确认无头像。 */
export type CharacterAvatarEntries = Record<string, string | null>;

interface CharacterAvatarState {
  entries: CharacterAvatarEntries;
  setAvatars: (response: CharacterAvatarsResponseDto) => void;
  reset: () => void;
}

export const useCharacterAvatarStore = create<CharacterAvatarState>((set) => ({
  entries: {},
  setAvatars: (response) =>
    set(() => {
      const entries: CharacterAvatarEntries = {};
      // 主Agent条目优先写入，子Agent条目不覆盖同名 key（主Agent优先防同名覆盖）。
      const main = response.main;
      if (main) entries[main.name] = main.avatar_url ?? null;
      for (const entry of response.characters) {
        if (!(entry.name in entries)) entries[entry.name] = entry.avatar_url ?? null;
      }
      return { entries };
    }),
  reset: () => set({ entries: {} }),
}));

/** 按角色名取头像 URL；未命中或未提供名称返回 null。返回值保持 string/null 引用稳定。 */
export function useCharacterAvatarUrl(name: string | undefined): string | null {
  return useCharacterAvatarStore((s) => (name ? s.entries[name] : undefined) ?? null);
}
