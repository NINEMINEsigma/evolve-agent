// 媒体实例清单的页大小、标签上限、刷新去抖和接口路径。
export const SESSION_MEDIA = {
  PAGE_SIZE: 100,
  MAX_PAGE_SIZE: 500,
  SOURCE_MAX_CHARS: 512,
  REFRESH_DEBOUNCE_MS: 250,
  // 视频没有原生loading=lazy；临近视口才挂载metadata预览，距离单位px。
  VIDEO_PREVIEW_ROOT_MARGIN: "200px",
  VIDEO_PREVIEW_THRESHOLD: 0,
  ID_PATTERN: /^[0-9a-f]{32}$/,
  API_PREFIX: "/api/sessions/",
  API_SUFFIX: "/history/media",
  CONTENT_SUFFIX: "/content",
} as const;
