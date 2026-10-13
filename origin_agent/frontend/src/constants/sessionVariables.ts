/** 会话变量显示与 SVG 布局约定，不裁剪服务端变量列表。 */
export const SESSION_VARIABLE_PRESENTATION = {
  MAX_SIGNIFICANT_DIGITS: 15,
  SAFE_NUMBER_MAX: Number.MAX_SAFE_INTEGER,
  GAUGE_RADIUS: 42,
  GAUGE_STROKE_WIDTH: 8,
  GAUGE_VIEWBOX_SIZE: 100,
  GAUGE_CENTER: 50,
} as const;

/** 服务端公开问题码的中文显示；未知码仍展示原英文说明。 */
export const SESSION_VARIABLE_ISSUE_LABELS: Readonly<Record<string, string>> = {
  invalid_json: "值不是有效的 JSON",
  unsupported_value: "仅支持 JSON 数字和字符串",
  non_finite_number: "数字必须是有限值",
  unsafe_number: "数字超出浏览器安全范围",
  invalid_utf8: "文件不是有效的 UTF-8 文本",
  value_read_error: "无法读取文件",
  file_changed: "读取过程中文件发生变化",
  file_too_large: "文件超出单文件大小上限",
  invalid_meta: "元数据格式无效或不是普通文件",
  invalid_boolean: "布尔配置只能为小写 true 或 false",
  invalid_number: "元数据必须是有限且安全的 JSON 数字",
  invalid_display: "显示方式只能为 auto、number、bar 或 gauge",
  invalid_range: "下限大于上限",
  metadata_too_long: "元数据显示文本过长",
  metadata_not_applicable: "字符串不支持数字专用配置",
  below_min: "当前值低于下限",
  above_max: "当前值高于上限",
  not_integer: "当前值不满足整数要求",
  unsafe_path: "不支持链接、重解析点或特殊文件",
  orphan_metadata: "元数据没有对应的变量文件",
};
