export interface ContextProgressBadgeProps {
  contextTokens: number;
  llmMaxContextTokens: number;
  tokenUsage: number;
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

export default function ContextProgressBadge({
  contextTokens,
  llmMaxContextTokens,
  tokenUsage,
}: ContextProgressBadgeProps) {
  if (llmMaxContextTokens <= 0) return null;

  const percent = clampPercent((contextTokens / llmMaxContextTokens) * 100);
  const tooltip = `累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens.toLocaleString()}`;

  return (
    <span
      className="context-progress-badge"
      data-tooltip={tooltip}
      role="img"
      aria-label={`上下文使用率 ${Math.round(percent)}%`}
    >
      <span className="context-progress-track" aria-hidden="true">
        <span className="context-progress-value" style={{ width: `${percent}%` }} />
      </span>
      <span className="context-progress-label">{Math.round(percent)}%</span>
    </span>
  );
}
