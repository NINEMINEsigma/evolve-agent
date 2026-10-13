import { SESSION_VARIABLE_PRESENTATION } from "../../constants/sessionVariables";
import type { AgentspaceEvent } from "../../types";
import type { SessionVariableEntryDto, VariableGroup } from "./types";

const format = new Intl.NumberFormat(undefined, {
  maximumSignificantDigits: SESSION_VARIABLE_PRESENTATION.MAX_SIGNIFICANT_DIGITS,
});

export function formatVariableNumber(value: number, percent: boolean): string {
  return format.format(percent ? value * 100 : value) + (percent ? "%" : "");
}

export function formatVariableValue(entry: SessionVariableEntryDto): string {
  if (entry.kind === "number" && typeof entry.value === "number") {
    return formatVariableNumber(entry.value, entry.metadata.percent);
  }
  if (entry.kind === "string" && typeof entry.value === "string") return entry.value;
  return "无法解析变量值";
}

export function getVariableRangeRatio(entry: SessionVariableEntryDto): number | null {
  const { min, max } = entry.metadata;
  if (entry.kind !== "number" || typeof entry.value !== "number" || min === null || max === null || min >= max) return null;
  // 先缩放避免极端范围差分，clamp仅控制绘图，不修改显示原值。
  const scale = Math.max(Math.abs(min), Math.abs(max), Math.abs(entry.value), 1);
  const ratio = (entry.value / scale - min / scale) / (max / scale - min / scale);
  if (!Number.isFinite(ratio)) return null;
  return Math.min(1, Math.max(0, ratio));
}

export function resolveVariableDisplay(entry: SessionVariableEntryDto): "number" | "bar" | "gauge" | "text" {
  if (entry.kind === "string") return "text";
  if (entry.kind === "invalid") return "number";
  const display = entry.metadata.display;
  if (display === "number" || getVariableRangeRatio(entry) === null) return "number";
  return display === "gauge" ? "gauge" : "bar";
}

function compareNames(left: string, right: string): number {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" }) || left.localeCompare(right);
}

export function buildVariableGroups(entries: readonly SessionVariableEntryDto[]): VariableGroup[] {
  const root: VariableGroup = { path: "", name: "未分组", entries: [], children: [] };
  const index = new Map<string, VariableGroup>([["", root]]);
  for (const entry of entries) {
    let parent = root;
    let path = "";
    for (const part of entry.group ? entry.group.split("/") : []) {
      path = path ? `${path}/${part}` : part;
      let group = index.get(path);
      if (!group) {
        group = { path, name: part, entries: [], children: [] };
        index.set(path, group);
        parent.children.push(group);
      }
      parent = group;
    }
    parent.entries.push(entry);
  }
  const sort = (group: VariableGroup) => {
    group.children.sort((left, right) => compareNames(left.name, right.name));
    group.entries.sort((left, right) => compareNames(left.id, right.id));
    group.children.forEach(sort);
  };
  sort(root);
  return root.entries.length ? [root] : root.children;
}

export function variableEventRelevant(event: AgentspaceEvent, sessionId: string): boolean {
  if (event.kind === "resync") return true;
  if (!sessionId || (event.kind !== "created" && event.kind !== "modified"
    && event.kind !== "deleted" && event.kind !== "moved")) return false;
  const root = `sessions/${sessionId}/variables`;
  return [event.path, event.new_path].some((candidate) => {
    if (candidate === null) return false;
    const path = candidate.replace(/\\/g, "/").replace(/\/+$/, "");
    return path === "" || path === root || path.startsWith(`${root}/`) || root.startsWith(`${path}/`);
  });
}
