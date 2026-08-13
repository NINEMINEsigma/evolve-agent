/** localStorage 键名 */
export const STORAGE_KEYS = {
  SESSION_ID:          "evolve_session_id",
  BUILD_HASH:          "evolve_build_hash",
  SUBAGENT_PANEL_WIDTH: "evolve_subagent_panel_width",

  // 全局 UI 偏好
  SIDEBAR_COLLAPSED:           "evolve_sidebar_collapsed",
  DRAWER_OPEN:                 "evolve_drawer_open",
  HEADER_COLLAPSED:            "evolve_header_collapsed",
  TASK_PROGRESS_COLLAPSED:     "evolve_task_progress_collapsed",
  CLIPBOARD_COLLAPSED:         "evolve_clipboard_collapsed",
  DRAWER_RESOURCES_EXPANDED:   "evolve_drawer_resources_expanded",
  DRAWER_BACKGROUND_EXPANDED:  "evolve_drawer_background_expanded",
  DRAWER_CRON_EXPANDED:        "evolve_drawer_cron_expanded",
  DRAWER_DYNENDPOINTS_EXPANDED:"evolve_drawer_dynendpoints_expanded",
  EXPANDED_CLUSTERS:           "evolve_expanded_clusters",
  HANDSFREE_MODE:              "evolve_handsfree_mode",

  // 按会话隔离
  SUBAGENT_PANEL_OPEN:    "evolve_subagent_panel_open",
  ACTIVE_SUBAGENT_ID:     "evolve_active_subagent_id",
  TARGET_SESSIONS:        "evolve_target_sessions",
  VISIBLE_CHARACTERS:    "evolve_visible_characters",
  RESPONSE_CHARACTERS:   "evolve_response_characters",
} as const;