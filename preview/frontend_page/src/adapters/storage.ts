import type { STORAGE_KEYS as OriginalStorageKeys } from "@preview-original/storage";
import { DIMENSIONS } from "@origin/constants/dimensions";
import { PREVIEW } from "../constants";
import type { PreviewOptions } from "../types";

export const STORAGE_KEYS = {
  SESSION_ID: `${PREVIEW.storagePrefix}session_id`,
  BUILD_HASH: `${PREVIEW.storagePrefix}build_hash`,
  SIDEBAR_WIDTH: `${PREVIEW.storagePrefix}sidebar_width`,
  SIDEBAR_COLLAPSED: `${PREVIEW.storagePrefix}sidebar_collapsed`,
  SHOW_SYSTEM_USER_MESSAGES: `${PREVIEW.storagePrefix}show_system_user_messages`,
  DRAWER_RESOURCES_EXPANDED: `${PREVIEW.storagePrefix}drawer_resources_expanded`,
  DRAWER_BACKGROUND_EXPANDED: `${PREVIEW.storagePrefix}drawer_background_expanded`,
  DRAWER_CRON_EXPANDED: `${PREVIEW.storagePrefix}drawer_cron_expanded`,
  DRAWER_DYNENDPOINTS_EXPANDED: `${PREVIEW.storagePrefix}drawer_dynendpoints_expanded`,
  EXPANDED_CLUSTERS: `${PREVIEW.storagePrefix}expanded_clusters`,
  AGENTSPACE_SIDEBAR_WIDTH: `${PREVIEW.storagePrefix}agentspace_sidebar_width`,
  AGENTSPACE_SIDEBAR_COLLAPSED: `${PREVIEW.storagePrefix}agentspace_sidebar_collapsed`,
  SESSION_LLM_PROFILE_PREFIX: `${PREVIEW.storagePrefix}session_llm_profile:`,
  ONBOARDING_COMPLETED: `${PREVIEW.storagePrefix}onboarding_completed`,
  ACTIVE_SUBAGENT_ID: `${PREVIEW.storagePrefix}active_subagent_id`,
  TARGET_SESSIONS: `${PREVIEW.storagePrefix}target_sessions`,
  VISIBLE_CHARACTERS: `${PREVIEW.storagePrefix}visible_characters`,
  RESPONSE_CHARACTERS: `${PREVIEW.storagePrefix}response_characters`,
  STAGE_PAUSED: `${PREVIEW.storagePrefix}stage_paused`,
  CHAT_STYLE_PAUSED: `${PREVIEW.storagePrefix}chat_style_paused`,
  CONN_TOKEN: `${PREVIEW.storagePrefix}conn_token`,
} as const satisfies Record<keyof typeof OriginalStorageKeys, string>;

export function initializePreviewStorage(options: PreviewOptions): void {
  // 只清理预览所有的命名空间，既不读取正式键的值，也不清空浏览器存储。
  for (const storage of [window.localStorage, window.sessionStorage]) {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index);
      if (key?.startsWith(PREVIEW.storagePrefix)) storage.removeItem(key);
    }
  }
  const storage = window.localStorage;
  const set = (key: string, value: unknown) => storage.setItem(key, JSON.stringify(value));
  storage.setItem(STORAGE_KEYS.SESSION_ID, options.sessionId);
  set(STORAGE_KEYS.SIDEBAR_WIDTH, DIMENSIONS.SIDEBAR_DEFAULT);
  set(STORAGE_KEYS.SIDEBAR_COLLAPSED, false);
  set(STORAGE_KEYS.AGENTSPACE_SIDEBAR_WIDTH, DIMENSIONS.AGENTSPACE_SIDEBAR_DEFAULT);
  set(STORAGE_KEYS.AGENTSPACE_SIDEBAR_COLLAPSED, false);
  set(STORAGE_KEYS.SHOW_SYSTEM_USER_MESSAGES, true);
  set(STORAGE_KEYS.DRAWER_RESOURCES_EXPANDED, true);
  set(STORAGE_KEYS.DRAWER_BACKGROUND_EXPANDED, true);
  set(STORAGE_KEYS.DRAWER_CRON_EXPANDED, true);
  set(STORAGE_KEYS.DRAWER_DYNENDPOINTS_EXPANDED, true);
  set(STORAGE_KEYS.EXPANDED_CLUSTERS, []);
  set(STORAGE_KEYS.TARGET_SESSIONS, { [options.sessionId]: ["main"] });
  set(STORAGE_KEYS.VISIBLE_CHARACTERS, { [options.sessionId]: ["all-agents"] });
  set(STORAGE_KEYS.RESPONSE_CHARACTERS, { [options.sessionId]: [] });
  set(STORAGE_KEYS.ACTIVE_SUBAGENT_ID, { [options.sessionId]: null });
  set(STORAGE_KEYS.STAGE_PAUSED, { [options.sessionId]: false });
  set(STORAGE_KEYS.CHAT_STYLE_PAUSED, { [options.sessionId]: false });
  set(`${STORAGE_KEYS.SESSION_LLM_PROFILE_PREFIX}${encodeURIComponent(options.sessionId)}`, PREVIEW.defaultProfile);
  if (options.scene !== "onboarding") storage.setItem(STORAGE_KEYS.ONBOARDING_COMPLETED, "true");
}
