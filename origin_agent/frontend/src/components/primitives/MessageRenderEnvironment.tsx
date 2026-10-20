/**
 * 消息渲染环境共享受限上下文。
 *
 * 正式聊天渲染路径默认运行在 live 模式：资源引用原样使用、原始 HTML 走
 * SafeHtml 隔离 iframe、iframe 走 IframeRenderer。
 *
 * 离线导出阅读器通过 MessageRenderProvider 注入 offline 环境：资源引用经
 * 本地资源表解析、原始 HTML 交给受限的离线隔离 frame、不支持的 iframe 只
 * 显示占位。没有 Provider 时保持既有 live 行为，正式路径零改动语义。
 */

import { createContext, useContext, type ReactNode } from "react";

export type MessageRenderMode = "live" | "offline";

/** 资源引用种类，离线环境据此选择解析策略。 */
export type MessageResourceKind = "image" | "audio" | "video" | "link";

/** 资源引用解析器：返回可加载引用，无法解析返回 null。 */
export type MessageResourceResolver = (raw: string, kind: MessageResourceKind) => string | null;

export interface MessageRenderEnvironment {
  mode: MessageRenderMode;
  /** 把原始资源引用解析为可加载的本地引用；无法解析返回 null。live 原样返回。 */
  resolveResource(raw: string, kind: MessageResourceKind): string | null;
  /** 渲染原始 HTML（live: SafeHtml；offline: 受限隔离 frame）。 */
  renderHtml(html: string, key?: string): ReactNode;
  /** 渲染 iframe 引用（live: IframeRenderer；offline: 占位或受限展示）。 */
  renderIframe(src: string, key?: string): ReactNode;
  /** 离线复制不可用时的报告回调；live 不提供。 */
  onCopyFailure?: () => void;
  /** 离线 Mermaid SVG 净化；live 不提供（保持既有 dangerouslySetInnerHTML 行为）。 */
  sanitizeSvg?: (svg: string) => string;
  /** 离线运行期问题上报（code + 详情）；live 不提供。 */
  reportIssue?: (code: string, detail: string) => void;
  /** 离线渲染标签（中文提示文本），由离线入口注入。 */
  labels?: {
    diagramFailed?: string;
    frameOpen?: string;
    attachment?: string;
    copyFailed?: string;
    resourceUnavailable?: string;
  };
}

const liveEnvironment: MessageRenderEnvironment = {
  mode: "live",
  resolveResource(raw: string) {
    return raw;
  },
  renderHtml() {
    return null;
  },
  renderIframe() {
    return null;
  },
};

const MessageRenderContext = createContext<MessageRenderEnvironment | null>(null);

export function MessageRenderProvider({
  environment,
  children,
}: {
  environment: MessageRenderEnvironment;
  children: ReactNode;
}) {
  return <MessageRenderContext.Provider value={environment}>{children}</MessageRenderContext.Provider>;
}

/** 读取当前渲染环境；无 Provider 时返回 live 默认环境。 */
export function useMessageRenderEnvironment(): MessageRenderEnvironment {
  return useContext(MessageRenderContext) ?? liveEnvironment;
}
