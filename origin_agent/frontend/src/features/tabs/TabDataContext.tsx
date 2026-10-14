import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import type { TabId } from "./registry";
import { useCharacterProfiles, type UseCharacterProfilesState } from "./useCharacterProfiles";
import { useDynamicSandboxSpaces, type UseDynamicSandboxSpacesState } from "./useDynamicSandboxSpaces";
import { useSessionMedia } from "../sessionMedia/useSessionMedia";
import { useSessionVariables } from "../sessionVariables/useSessionVariables";
import type { UseSessionMediaState } from "../sessionMedia/types";
import type { UseSessionVariablesState } from "../sessionVariables/useSessionVariables";

export interface TabDataContextValue {
  characters: UseCharacterProfilesState;
  sandbox: UseDynamicSandboxSpacesState;
  media: UseSessionMediaState;
  variables: UseSessionVariablesState;
}

const TabDataContext = createContext<TabDataContextValue | null>(null);

interface TabDataProviderProps {
  activeTab: TabId;
  sessionId: string;
  currentSessionArchived: boolean;
  children: ReactNode;
}

/**
 * 唯一 Provider：为 characters / sandbox 两个全局列表与 media / variables 两个
 * 会话级快照各持有一个 hook 实例，供正式 Tab 页面与只读预览共享同一份已加载数据。
 * 不输出 DOM、不随普通 Tab 切换或主会话切换重建（仅随锁定分支卸载）。
 */
export function TabDataProvider({ activeTab, sessionId, currentSessionArchived, children }: TabDataProviderProps) {
  const characters = useCharacterProfiles(activeTab === "characters");
  const sandbox = useDynamicSandboxSpaces();
  const media = useSessionMedia(sessionId, activeTab === "media", currentSessionArchived);
  const variables = useSessionVariables(sessionId, activeTab === "variables");

  const value = useMemo<TabDataContextValue>(
    () => ({ characters, sandbox, media, variables }),
    [characters, sandbox, media, variables],
  );

  return <TabDataContext.Provider value={value}>{children}</TabDataContext.Provider>;
}

/** 显式访问 hook：缺 Provider 视为编程错误快速失败，不创建第二份数据。 */
export function useTabData(): TabDataContextValue {
  const value = useContext(TabDataContext);
  if (value === null) throw new Error("useTabData must be used within TabDataProvider");
  return value;
}