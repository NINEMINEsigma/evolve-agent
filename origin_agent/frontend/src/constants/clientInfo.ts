/** 前端版本标识 */
export const FRONTEND_VERSION = "EvolveAgent-Web/v1.0";

/**
 * 收集客户端设备信息，随 USER_MESSAGE 发送给后端。
 */
export function collectClientInfo(): Record<string, string> {
  const ua = navigator.userAgent;
  const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
  const isTablet = /iPad|Tablet/i.test(ua);

  let deviceType = "desktop";
  if (isTablet) deviceType = "tablet";
  else if (isMobile) deviceType = "mobile";

  let orientation = "unknown";
  try {
    orientation = screen.orientation?.type ?? "unknown";
  } catch {
    orientation = "unknown";
  }

  return {
    device_type: deviceType,
    browser: ua,
    frontend_version: FRONTEND_VERSION,
    screen_orientation: orientation,
  };
}