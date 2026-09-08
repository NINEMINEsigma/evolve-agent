/**
 * Agent 舞台层 — 聊天区背景层的会话级渲染组件。
 *
 * 基于 useSessionStage hook 探测当前会话的 stage/index.html，
 * 存在时以透明 iframe 渲染，默认鼠标穿透。
 *
 * sandbox 策略：allow-scripts allow-same-origin。
 * 比 SafeHtml 和 SessionSiteDrawer 更严格（去掉 allow-popups 和 allow-forms），
 * 因为舞台层是背景层，不接收用户交互。
 * 需要 allow-same-origin 以加载 assets/ 下的图集资源和 fetch 本地文件。
 */

import { useSessionStage } from "../hooks/useSessionStage";

interface AgentStageLayerProps {
  sessionId: string | undefined;
}

export default function AgentStageLayer({ sessionId }: AgentStageLayerProps) {
  const { status, reloadKey, stageUrl } = useSessionStage(sessionId);

  if (status !== "ready" || !stageUrl) return null;

  return (
    <div className="agent-stage-layer">
      <iframe
        key={reloadKey}
        src={stageUrl}
        sandbox="allow-scripts allow-same-origin"
        title="agent-stage"
      />
    </div>
  );
}
