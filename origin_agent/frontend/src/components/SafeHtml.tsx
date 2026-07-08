/**
 * 在 assistant 消息气泡中直接渲染 AI 输出的原始 HTML。
 *
 * 本项目为本地部署 + 个人使用场景，此处不做任何过滤，
 * 允许 script、style、iframe、事件处理器等全部 HTML/JS/CSS 功能，
 * 以便 agent 可在气泡内嵌入完整交互组件（如小游戏、状态面板等）。
 */

interface SafeHtmlProps {
  html: string;
  className?: string;
}

export default function SafeHtml({ html, className }: SafeHtmlProps) {
  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}