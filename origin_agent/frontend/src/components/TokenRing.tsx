/**
 * 上下文用量环形徽章（TokenRing）
 *
 * 从 Header.tsx 提取为独立组件，供 Header 与 InputBar 共用。
 * 环形 SVG + 中央百分比；llmMaxContextTokens <= 0 时返回 null。
 * data-tooltip 悬浮显示累计消耗 / 已用上下文 / 最大上下文三项。
 */

interface TokenRingProps {
  contextTokens: number;
  llmMaxContextTokens: number;
  tokenUsage: number;
}

export default function TokenRing({
  contextTokens,
  llmMaxContextTokens,
  tokenUsage,
}: TokenRingProps) {
  const percent =
    llmMaxContextTokens > 0
      ? Math.round((contextTokens / llmMaxContextTokens) * 100)
      : 0;
  const R = 12;
  const C = 2 * Math.PI * R;
  const offset = C * (1 - percent / 100);

  if (llmMaxContextTokens <= 0) return null;

  return (
    <span
      className="token-ring"
      data-tooltip={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}
    >
      <svg viewBox="0 0 32 32" width="28" height="28">
        <circle
          className="token-ring-track"
          cx="16"
          cy="16"
          r={R}
        />
        <circle
          className="token-ring-progress"
          cx="16"
          cy="16"
          r={R}
          style={{ strokeDashoffset: offset }}
        />
      </svg>
      <span className="token-ring-label">{percent}</span>
    </span>
  );
}