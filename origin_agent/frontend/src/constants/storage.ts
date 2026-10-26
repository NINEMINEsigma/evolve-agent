/** 存储键名（介质由调用方决定：localStorage 或 sessionStorage） */
export const STORAGE_KEYS = {
  SESSION_ID:          "evolve_session_id",
  BUILD_HASH:          "evolve_build_hash",
  SIDEBAR_WIDTH:              "evolve_sidebar_width",

  // 全局 UI 偏好
  SIDEBAR_COLLAPSED:           "evolve_sidebar_collapsed",
  // system 角色用户消息是否显示；默认 true，所有会话共用。
  SHOW_SYSTEM_USER_MESSAGES:   "evolve_show_system_user_messages",
  CLIPBOARD_COLLAPSED:         "evolve_clipboard_collapsed",
  DRAWER_RESOURCES_EXPANDED:   "evolve_drawer_resources_expanded",
  DRAWER_BACKGROUND_EXPANDED:  "evolve_drawer_background_expanded",
  DRAWER_CRON_EXPANDED:        "evolve_drawer_cron_expanded",
  DRAWER_DYNENDPOINTS_EXPANDED:"evolve_drawer_dynendpoints_expanded",
  EXPANDED_CLUSTERS:           "evolve_expanded_clusters",
  AGENTSPACE_SIDEBAR_WIDTH:    "evolve_agentspace_sidebar_width",
  AGENTSPACE_SIDEBAR_COLLAPSED:"evolve_agentspace_sidebar_collapsed",

  // LLM 模型配置
  // 每会话单独保存待用名称；旧全局键不猜测迁移。
  SESSION_LLM_PROFILE_PREFIX: "evolve_session_llm_profile:",

  // 首次引导向导完成标志
  ONBOARDING_COMPLETED: "evolve_onboarding_completed",

  // 按会话隔离
  ACTIVE_SUBAGENT_ID:     "evolve_active_subagent_id",
  TARGET_SESSIONS:        "evolve_target_sessions",
  VISIBLE_CHARACTERS:    "evolve_visible_characters",
  RESPONSE_CHARACTERS:   "evolve_response_characters",

  // 会话视觉暂停开关（按会话隔离）
  STAGE_PAUSED:           "evolve_stage_paused",
  CHAT_STYLE_PAUSED:      "evolve_chat_style_paused",

  // 会话锁定（sessionStorage，标签页级别）
  CONN_TOKEN:            "evolve_conn_token",
} as const;