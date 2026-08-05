/** 超时/间隔常量 (ms) */
export const TIMING = {
  BANNER_TTL:            60_000,  // SecretBanner 自动消失
  TOOLTIP_HIDE_DELAY:    80,      // tooltip 延迟隐藏
  WS_KEEPALIVE:          20_000,  // WebSocket keepalive 间隔
  WS_RECONNECT_BASE:     1_000,   // WebSocket 重连延迟基数
  WS_MAX_RECONNECT_DELAY: 30_000, // WebSocket 最大重连延迟
  WS_MAX_RECONNECT_TRIES: 10,     // WebSocket 最大重连次数
  TASK_POLL_INTERVAL:    3_000,   // 后台任务轮询
  LOCK_POLL_INTERVAL:    3_000,   // agentspace 锁状态轮询
  CRON_TICK:             1_000,   // 定时任务倒计时 tick
  CRON_WINDOW:           60_000,  // 定时任务倒计时显示窗口
  COPY_RESET_DELAY:      2_000,   // 复制成功状态复位
  DIAGNOSTICS_TICK:      500,     // 诊断 tick
  SPLASH_MIN_DISPLAY:    800,     // 启动屏最小显示
  SPLASH_MAX_DISPLAY:    3_000,   // 启动屏最大显示
  SPLASH_FADE_DELAY:     500,     // 启动屏淡出
  RECV_STALL_ACTIVE:     2_000,   // 接收停滞阈值（活跃）
  RECV_STALL_INACTIVE:   30_000,  // 接收停滞阈值（非活跃）
  PONG_STALL:            35_000,  // Pong 停滞阈值
  EDGE_DRAWER_CLOSE:     400,     // 边缘抽屉关闭延迟
  EDGE_DRAWER_PEEK:      250,     // 边缘抽屉 peek 延迟
  INPUT_DEBOUNCE:        180,     // 输入防抖
  MENU_SCROLL_DEBOUNCE:  150,     // 菜单滚动防抖
} as const;