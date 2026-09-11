/**
 * 聊天区自定义样式层 — 会话级 CSS 作用域注入组件。
 *
 * 接收 useSessionChatStyle hook 产出的 cssText，以 <style> 标签注入
 * 到 ChatArea 根节点内部。作用域处理后的 CSS 只包含 .chat-area 前缀
 * 的选择器和全局 @font-face / @keyframes。
 *
 * 状态为 error 或 missing 时不注入任何样式，聊天区使用默认样式。
 * 组件卸载时移除 <style> 标签。
 */

import { useEffect, useRef } from "react";
import type { ChatStyleStatus } from "../hooks/useSessionChatStyle";

interface ChatStyleLayerProps {
  /** 作用域处理后的 CSS 文本，null 时不注入 */
  cssText: string | null;
  /** 加载状态 */
  status: ChatStyleStatus;
  /** 热重载 key，变化时更新 <style> 内容 */
  reloadKey: number;
}

export default function ChatStyleLayer({ cssText, status, reloadKey }: ChatStyleLayerProps) {
  const styleRef = useRef<HTMLStyleElement | null>(null);

  useEffect(() => {
    // 状态为 ready 且有 cssText 时注入或更新
    if (status === "ready" && cssText) {
      if (!styleRef.current) {
        const styleEl = document.createElement("style");
        styleEl.setAttribute("data-chat-style-scope", "");
        styleRef.current = styleEl;
        document.head.appendChild(styleEl);
      }
      styleRef.current.textContent = cssText;
    } else {
      // 非 ready 状态：移除已有 <style>
      if (styleRef.current) {
        styleRef.current.remove();
        styleRef.current = null;
      }
    }

    // 组件卸载时清理
    return () => {
      if (styleRef.current) {
        styleRef.current.remove();
        styleRef.current = null;
      }
    };
  }, [cssText, status, reloadKey]);

  // 此组件不渲染可见 DOM，仅通过 <style> 标签注入 CSS
  return null;
}
