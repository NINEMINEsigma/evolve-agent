/** Round navigation rail constants. */

// 条目固定行高（px），轮次导航条虚拟列表使用；与 styles/round-nav.css 的 .round-nav-entry 高度保持同步
export const ROUND_NAV_ENTRY_HEIGHT_PX = 28;
// 跳转后目标消息顶部距视口顶部的视口高度比例（视口中部略偏上的舒适位置）
export const ROUND_NAV_JUMP_OFFSET_RATIO = 0.35;
// 近平滑/远瞬时的行距阈值（展示行数）
export const ROUND_NAV_NEAR_JUMP_ROWS = 20;
// 条目文本前端截断字符数
export const ROUND_NAV_EXCERPT_MAX_CHARS = 60;
// 条目 tooltip 全文截断字符数
export const ROUND_NAV_TOOLTIP_MAX_CHARS = 200;
