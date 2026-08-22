/** 存储键名（介质由调用方决定：localStorage 或 sessionStorage） */
export const STORAGE_KEYS = {
  SESSION_ID:          "evolve_session_id",
  BUILD_HASH:          "evolve_build_hash",
  SUBAGENT_PANEL_WIDTH: "evolve_subagent_panel_width",
  SIDEBAR_WIDTH:              "evolve_sidebar_width",
  DRAWER_WIDTH:               "evolve_drawer_width",

  // 全局 UI 偏好
  SIDEBAR_COLLAPSED:           "evolve_sidebar_collapsed",
  DRAWER_OPEN:                 "evolve_drawer_open",
  LLM_DRAWER_OPEN:             "evolve_llm_drawer_open",
  LLM_DRAWER_WIDTH:            "evolve_llm_drawer_width",
  HEADER_COLLAPSED:            "evolve_header_collapsed",
  TASK_PROGRESS_COLLAPSED:     "evolve_task_progress_collapsed",
  CLIPBOARD_COLLAPSED:         "evolve_clipboard_collapsed",
  DRAWER_RESOURCES_EXPANDED:   "evolve_drawer_resources_expanded",
  DRAWER_BACKGROUND_EXPANDED:  "evolve_drawer_background_expanded",
  DRAWER_CRON_EXPANDED:        "evolve_drawer_cron_expanded",
  DRAWER_DYNENDPOINTS_EXPANDED:"evolve_drawer_dynendpoints_expanded",
  EXPANDED_CLUSTERS:           "evolve_expanded_clusters",
  HANDSFREE_MODE:              "evolve_handsfree_mode",

  // LLM 模型配置
  // LEGACY：仅供 localStorage→agentspace 迁移读取，下轮清理删除
  LLM_PROFILES:        "evolve_llm_profiles",
  ACTIVE_LLM_PROFILE:  "evolve_active_llm_profile",

  // 按会话隔离
  SUBAGENT_PANEL_OPEN:    "evolve_subagent_panel_open",
  ACTIVE_SUBAGENT_ID:     "evolve_active_subagent_id",
  TARGET_SESSIONS:        "evolve_target_sessions",
  VISIBLE_CHARACTERS:    "evolve_visible_characters",
  RESPONSE_CHARACTERS:   "evolve_response_characters",

  // 会话锁定（sessionStorage，标签页级别）
  CONN_TOKEN:            "evolve_conn_token",
} as const;