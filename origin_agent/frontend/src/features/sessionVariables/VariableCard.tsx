import { useState } from "react";
import type { ReactElement } from "react";
import JsonView from "react18-json-view";
import "react18-json-view/src/style.css";
import { SESSION_VARIABLE_ISSUE_LABELS, SESSION_VARIABLE_PRESENTATION as geometry } from "../../constants/sessionVariables";
import { formatVariableNumber, formatVariableValue, getVariableRangeRatio, resolveVariableDisplay } from "./presentation";
import type { SessionVariableEntryDto, SessionVariableIssueDto } from "./types";

export function VariableIssues({ issues }: { issues: readonly SessionVariableIssueDto[] }): ReactElement {
  return <ul className="session-variable-issues">
    {issues.map((issue, index) => <li key={`${issue.path}:${issue.code}:${issue.key ?? ""}:${index}`} data-issue-kind={issue.kind}>
      <span>{SESSION_VARIABLE_ISSUE_LABELS[issue.code] ?? issue.message}</span>
      <code>{issue.path}{issue.key ? ` [${issue.key}]` : ""}</code>
    </li>)}
  </ul>;
}

/** 原始 JSON 视图的对象：以 raw 原文为准，规范化字段仅补齐缺失部分。 */
function buildRawEntryObject(entry: SessionVariableEntryDto): Record<string, unknown> {
  const raw: Record<string, unknown> = {};
  if (entry.raw_value !== null) raw.value = entry.raw_value;
  if (entry.raw_metadata !== null) raw.metadata = entry.raw_metadata;
  return {
    id: entry.id, kind: entry.kind, group: entry.group,
    value: entry.value, metadata: entry.metadata,
    ...(Object.keys(raw).length > 0 ? { raw } : {}),
    issues: entry.issues.length > 0 ? entry.issues : undefined,
  };
}

export default function VariableCard({ entry }: { entry: SessionVariableEntryDto }): ReactElement {
  const [showRawJson, setShowRawJson] = useState(false);
  const display = resolveVariableDisplay(entry);
  const ratio = getVariableRangeRatio(entry);
  const { min, max, percent } = entry.metadata;
  const valueText = formatVariableValue(entry);
  const hasConstraint = entry.issues.some((issue) => issue.kind === "constraint");
  const circumference = 2 * Math.PI * geometry.GAUGE_RADIUS;
  const numeric = typeof entry.value === "number" ? entry.value : null;
  // 只有值和双边范围都有效时才使用progressbar语义；越界值不伪造合法刻度。
  const accessibleRange = numeric !== null && min !== null && max !== null && min < max
    && numeric >= min && numeric <= max;
  const fallback = entry.kind === "number" && (entry.metadata.display === "bar" || entry.metadata.display === "gauge") && ratio === null;
  const accessibilityLabel = accessibleRange
    ? entry.metadata.label
    : `${entry.metadata.label}: ${valueText}${hasConstraint ? "，超出约束" : ""}`;

  return <article className={`session-variable-card${hasConstraint ? " has-constraint" : ""}${entry.kind === "invalid" ? " is-invalid" : ""}`}>
    <header className="session-variable-heading">
      <strong>{entry.metadata.label}</strong>
      <span>{entry.kind === "string" ? "字符串" : entry.kind === "number" ? "数字" : "无效值"}</span>
    </header>
    {entry.metadata.description && <p className="session-variable-description">{entry.metadata.description}</p>}
    {showRawJson ? (
      <div className="session-variable-json-view">
        <JsonView src={buildRawEntryObject(entry)} collapsed={1} displaySize collapseStringsAfterLength={99999} />
      </div>
    ) : (<>
      <div className={`session-variable-value session-variable-value--${display}`}>{valueText}</div>
      {display === "bar" && ratio !== null && <div
        className="session-variable-bar"
        role={accessibleRange ? "progressbar" : "img"}
        aria-label={accessibilityLabel}
        aria-valuenow={accessibleRange && numeric !== null ? numeric : undefined}
        aria-valuemin={accessibleRange && min !== null ? min : undefined}
        aria-valuemax={accessibleRange && max !== null ? max : undefined}
        aria-valuetext={accessibleRange ? valueText : undefined}
      >
        <div className="session-variable-bar-fill" style={{ width: `${ratio * 100}%` }} />
      </div>}
      {display === "gauge" && ratio !== null && <svg
        className="session-variable-gauge"
        viewBox={`0 0 ${geometry.GAUGE_VIEWBOX_SIZE} ${geometry.GAUGE_VIEWBOX_SIZE}`}
        role={accessibleRange ? "progressbar" : "img"}
        aria-label={accessibilityLabel}
        aria-valuenow={accessibleRange && numeric !== null ? numeric : undefined}
        aria-valuemin={accessibleRange && min !== null ? min : undefined}
        aria-valuemax={accessibleRange && max !== null ? max : undefined}
        aria-valuetext={accessibleRange ? valueText : undefined}
      >
        <circle className="session-variable-gauge-track" cx={geometry.GAUGE_CENTER} cy={geometry.GAUGE_CENTER} r={geometry.GAUGE_RADIUS} strokeWidth={geometry.GAUGE_STROKE_WIDTH} />
        <circle className="session-variable-gauge-fill" cx={geometry.GAUGE_CENTER} cy={geometry.GAUGE_CENTER} r={geometry.GAUGE_RADIUS}
          strokeWidth={geometry.GAUGE_STROKE_WIDTH} strokeDasharray={circumference} strokeDashoffset={circumference * (1 - ratio)}
          transform={`rotate(-90 ${geometry.GAUGE_CENTER} ${geometry.GAUGE_CENTER})`} />
      </svg>}
      {entry.kind === "number" && (min !== null || max !== null) && <div className="session-variable-range">
        下限 {min === null ? "未配置" : formatVariableNumber(min, percent)} · 上限 {max === null ? "未配置" : formatVariableNumber(max, percent)}
      </div>}
      {fallback && <p className="session-variable-note">缺少有效范围，已使用数值展示。</p>}
      {entry.kind === "invalid" && entry.raw_value !== null && <pre className="session-variable-raw">{entry.raw_value}</pre>}
      {entry.issues.length > 0 && <VariableIssues issues={entry.issues} />}
    </>)}
    <div className="session-variable-actions">
      <button
        type="button"
        className="session-variable-view-toggle"
        aria-pressed={showRawJson}
        title={showRawJson ? "切换至默认预览" : "切换至原始 JSON"}
        onClick={() => setShowRawJson((current) => !current)}
      >原始 JSON</button>
    </div>
  </article>;
}
