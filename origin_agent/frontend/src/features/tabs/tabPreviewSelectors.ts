/**
 * Pure tab preview selectors. Every selector consumes only already-loaded
 * snapshots from TabPreviewInput and returns a plain TabPreviewModel; no
 * selector performs requests, refreshes or mutations.
 */
import type { CronTask, SubagentSession } from "../../types";
import { TAB_PREVIEW, TAB_PREVIEW_LABELS as L } from "../../constants/tabPreview";
import type {
  TabPreviewInput, TabPreviewModel, TabPreviewNextEvent, TabPreviewRow, TabPreviewSection,
} from "./tabPreviewTypes";

/** 按 Unicode 码点截断并加省略号；负上限按 0 处理。不解析 HTML/Markdown。 */
export function truncatePreviewText(value: string, maxChars: number): string {
  const points = Array.from(value);
  if (maxChars <= 0 || points.length <= maxChars) return value;
  return `${points.slice(0, maxChars).join("")}…`;
}

/** 紧凑倒计时：小时/分钟/秒，负值钳为 0。 */
export function formatPreviewCountdown(remainingMs: number): string {
  const totalSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return minutes > 0 ? `${hours}h${minutes}m` : `${hours}h`;
  if (minutes > 0) return seconds > 0 ? `${minutes}m${seconds}s` : `${minutes}m`;
  return `${seconds}s`;
}

/** 内联载荷字符数的有限分组显示（保留“字符”语义，不换算为字节）。 */
export function formatPreviewPayloadChars(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** 数量占总数比例，返回 0–100 的有限百分比；total 为 0 时返回 0。 */
export function formatPreviewRatio(count: number, total: number): number {
  if (!Number.isFinite(count) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, (count / total) * 100));
}

function row(key: string, label: string, value: string, tone: TabPreviewRow["tone"] = "normal"): TabPreviewRow {
  return { key, label, value, tone };
}

function noticeSection(key: string, notice: string): TabPreviewSection {
  return { key, title: null, rows: [], notice };
}

function countText(value: number | null): string {
  return value === null ? L.unknown : String(value);
}

/** 最近一项普通 Cron / WaitCron：共同按 nextAt 升序，task_id 字典序打破并列。 */
export function selectNextCronEvent(tasks: readonly CronTask[], now: number): TabPreviewNextEvent | null {
  const candidates = tasks
    .filter((task) => task.should_schedule && task.next_run !== null)
    .map((task) => ({ task, nextAt: new Date(task.next_run as string).getTime() }))
    .filter(({ nextAt }) => Number.isFinite(nextAt))
    .sort((a, b) => a.nextAt - b.nextAt || a.task.task_id.localeCompare(b.task.task_id));
  const next = candidates[0];
  if (!next) return null;
  const remainingMs = next.nextAt - now;
  const reminder = next.task.is_wait === true && next.task.wait_message
    ? truncatePreviewText(next.task.wait_message, TAB_PREVIEW.REMINDER_MAX_CHARS)
    : null;
  return {
    taskId: next.task.task_id,
    name: truncatePreviewText(next.task.name || next.task.task_id, TAB_PREVIEW.TEXT_MAX_CHARS),
    kind: next.task.is_wait === true ? "wait" : "cron",
    nextAt: next.nextAt,
    remainingMs,
    reminder,
    due: remainingMs <= 0,
  };
}

function nextEventSection(event: TabPreviewNextEvent | null, known: boolean): TabPreviewSection[] {
  if (event === null) {
    return [noticeSection("next-event", known ? L.noScheduledTask : L.notLoaded)];
  }
  const rows: TabPreviewRow[] = [
    row("event-name", event.kind === "wait" ? L.waitEvent : L.cronEvent, event.name),
    row("trigger-at", L.triggerAt, new Date(event.nextAt).toLocaleString()),
  ];
  if (event.due) {
    rows.push(row("remaining", L.remaining, L.duePending, "warning"));
  } else {
    rows.push(row("remaining", L.remaining, formatPreviewCountdown(event.remainingMs)));
  }
  if (event.reminder) rows.push(row("reminder", L.reminder, event.reminder));
  return [{ key: "next-event", title: null, rows, notice: null }];
}

function section(key: string, rows: TabPreviewRow[], title: string | null = null, notice: string | null = null): TabPreviewSection {
  return { key, title, rows, notice };
}

export function selectChatPreview(input: TabPreviewInput): TabPreviewModel {
  const rows: TabPreviewRow[] = [];
  if (input.sessionArchived === true) rows.push(row("status", L.chatStatus, L.archived, "warning"));
  else if (input.sessionArchived === null || input.processing === null) rows.push(row("status", L.chatStatus, L.unknown, "muted"));
  else rows.push(row("status", L.chatStatus, input.processing ? L.busy : L.idle));
  const profile = input.llm.selectionStatus === "ready"
    ? (input.llm.pendingProfileName || L.noProfile)
    : input.llm.selectionStatus === "loading" ? L.loading : L.unknown;
  rows.push(row("pending-profile", L.pendingProfile, profile, input.llm.selectionStatus === "ready" ? "normal" : "muted"));
  return { sections: [section("chat", rows)], nextEvent: null, footnote: L.openTabHint };
}

export function selectResourcesPreview(input: TabPreviewInput): TabPreviewModel {
  const sections: TabPreviewSection[] = [];
  const resources = input.resources;
  if (resources === null) {
    sections.push(noticeSection("resources", L.notLoaded));
  } else {
    const rows: TabPreviewRow[] = [];
    if (resources.error !== null) rows.push(row("resources-error", L.readFailed, L.readFailed, "warning"));
    rows.push(row("images", L.images, String(resources.images)));
    rows.push(row("files", L.files, String(resources.downloads)));
    sections.push(section("resources", rows));
  }
  const shellData = input.shells.data;
  const cronData = input.cronTasks.data;
  const endpointData = input.dynamicEndpoints.data;
  const runtimeRows: TabPreviewRow[] = [
    row("shells", L.shells, countText(shellData === null ? null : shellData.length), shellData === null ? "muted" : "normal"),
  ];
  if (shellData !== null) {
    runtimeRows.push(row("running-shells", L.runningShells, String(shellData.filter((s) => s.running).length)));
  }
  runtimeRows.push(row("cron", L.cronTasks, countText(cronData === null ? null : cronData.length), cronData === null ? "muted" : "normal"));
  if (cronData !== null) {
    runtimeRows.push(row("scheduled-cron", L.scheduledCronTasks, String(cronData.filter((t) => t.should_schedule).length)));
  }
  runtimeRows.push(row("endpoints", L.dynamicEndpoints, countText(endpointData === null ? null : endpointData.length), endpointData === null ? "muted" : "normal"));
  sections.push(section("runtime", runtimeRows));
  const nextEvent = cronData === null ? null : selectNextCronEvent(cronData, input.now);
  sections.push(...nextEventSection(nextEvent, cronData !== null));
  return { sections, nextEvent, footnote: L.openTabHint };
}

export function selectSubagentsPreview(input: TabPreviewInput): TabPreviewModel {
  const items = Object.values(input.subagents) as SubagentSession[];
  const rows: TabPreviewRow[] = [
    row("total", L.subagents, String(items.length)),
    row("running", L.running, String(items.filter((s) => s.status === "running").length)),
    row("completed", L.completed, String(items.filter((s) => s.status === "completed").length)),
    row("terminated", L.terminated, String(items.filter((s) => s.status === "terminated").length)),
  ];
  return { sections: [section("subagents", rows)], nextEvent: null, footnote: L.openTabHint };
}

export function selectCharactersPreview(input: TabPreviewInput): TabPreviewModel {
  const profiles = input.characters.profiles;
  if (profiles === null) {
    const notice = input.characters.loading ? L.loading : input.characters.error !== null ? L.readFailed : L.notLoaded;
    return { sections: [noticeSection("characters", notice)], nextEvent: null, footnote: L.openTabHint };
  }
  const available = profiles.filter((entry) => entry.profile_available).length;
  const rows: TabPreviewRow[] = [
    row("total", L.characters, String(profiles.length)),
    row("available", L.available, String(available)),
    row("unavailable", L.unavailable, String(profiles.length - available), available === profiles.length ? "normal" : "warning"),
    row("roleplay", L.roleplay, String(profiles.filter((entry) => entry.character_type === "roleplay").length)),
    row("task", L.task, String(profiles.filter((entry) => entry.character_type === "task").length)),
  ];
  return {
    sections: [section("characters", rows, null, L.cachedSnapshot)],
    nextEvent: null,
    footnote: L.openTabHint,
  };
}

export function selectSitePreview(input: TabPreviewInput): TabPreviewModel {
  const ready = input.site.status === "ready";
  const rows: TabPreviewRow[] = [
    row("status", L.siteStatus, ready ? L.available : L.unavailable, ready ? "normal" : "muted"),
  ];
  if (ready && input.site.indexUrl) {
    rows.push(row("url", L.siteUrl, truncatePreviewText(input.site.indexUrl, TAB_PREVIEW.TEXT_MAX_CHARS)));
  }
  return { sections: [section("site", rows)], nextEvent: null, footnote: L.openTabHint };
}

function referenceText(status: string, name: string | null, available: boolean): string {
  if (status !== "ready") return status === "loading" ? L.loading : L.unknown;
  if (!name) return L.noProfile;
  return available ? name : `${name}（${L.unavailable}）`;
}

export function selectLlmPreview(input: TabPreviewInput): TabPreviewModel {
  const llm = input.llm;
  const rows: TabPreviewRow[] = [];
  if (llm.profilesStatus === "ready") rows.push(row("profiles", L.llmProfiles, String(llm.profilesCount ?? 0)));
  else if (llm.profilesStatus === "loading") rows.push(row("profiles", L.llmProfiles, L.loading, "muted"));
  else rows.push(row("profiles", L.llmProfiles, L.unknown, "muted"));
  const pending = llm.selectionStatus === "ready"
    ? (llm.pendingProfileName || L.noProfile)
    : llm.selectionStatus === "loading" ? L.loading : L.unknown;
  rows.push(row("pending", L.pendingProfile, pending, llm.selectionStatus === "ready" ? "normal" : "muted"));
  rows.push(row("approval", L.approvalProfile, referenceText(llm.approvalStatus, llm.approvalProfileName, llm.approvalAvailable)));
  rows.push(row("metadata", L.metadataProfile, referenceText(llm.metadataStatus, llm.metadataProfileName, llm.metadataAvailable)));
  const notice = llm.profilesStatus === "ready" && llm.profilesWarning !== null ? L.cachedSnapshot : null;
  return { sections: [section("llm", rows, null, notice)], nextEvent: null, footnote: L.openTabHint };
}

export function selectSandboxPreview(input: TabPreviewInput): TabPreviewModel {
  const spaces = input.sandbox.spaces;
  if (spaces === null) {
    const notice = input.sandbox.loading ? L.loading : input.sandbox.error !== null ? L.readFailed : L.notLoaded;
    return { sections: [noticeSection("sandbox", notice)], nextEvent: null, footnote: L.openTabHint };
  }
  const available = spaces.filter((space) => space.available).length;
  const readonly = spaces.filter((space) => space.is_readonly).length;
  const rows: TabPreviewRow[] = [
    row("total", L.sandboxSpaces, String(spaces.length)),
    row("available", L.available, String(available), available === spaces.length ? "normal" : "warning"),
    row("unavailable", L.unavailable, String(spaces.length - available)),
    row("readonly", L.readonlySpaces, String(readonly)),
    row("writable", L.writableSpaces, String(spaces.length - readonly)),
  ];
  const notice = input.sandbox.error !== null ? L.cachedSnapshot : null;
  return { sections: [section("sandbox", rows, null, notice)], nextEvent: null, footnote: L.openTabHint };
}

export function selectMediaPreview(input: TabPreviewInput): TabPreviewModel {
  const media = input.media;
  const aggregate = media.aggregate;
  if (aggregate === null) {
    const notice = media.loading ? L.loading : media.error !== null ? L.readFailed : L.mediaNotLoaded;
    return { sections: [noticeSection("media", notice)], nextEvent: null, footnote: L.openTabHint };
  }
  if (aggregate.total_count === 0) {
    return { sections: [noticeSection("media", L.mediaEmpty)], nextEvent: null, footnote: L.openTabHint };
  }
  const percent = (count: number) => `${Math.round(formatPreviewRatio(count, aggregate.total_count))}%`;
  const rows: TabPreviewRow[] = [
    row("media-enabled", L.mediaEnabled, `${aggregate.enabled_count} · ${percent(aggregate.enabled_count)}`),
    row("enabled-payload", L.inlinePayloadChars, formatPreviewPayloadChars(aggregate.enabled_inline_payload_chars)),
    row("enabled-unknown", L.unknownPayload, String(aggregate.enabled_unknown_payload_count), aggregate.enabled_unknown_payload_count > 0 ? "muted" : "normal"),
    row("media-disabled", L.mediaDisabled, `${aggregate.disabled_count} · ${percent(aggregate.disabled_count)}`),
    row("disabled-payload", L.inlinePayloadChars, formatPreviewPayloadChars(aggregate.disabled_inline_payload_chars)),
    row("disabled-unknown", L.unknownPayload, String(aggregate.disabled_unknown_payload_count), aggregate.disabled_unknown_payload_count > 0 ? "muted" : "normal"),
  ];
  const notice = media.error !== null || media.stale ? L.cachedSnapshot : null;
  return { sections: [section("media", rows, null, notice)], nextEvent: null, footnote: L.openTabHint };
}

export function selectVariablesPreview(input: TabPreviewInput): TabPreviewModel {
  const variables = input.variables;
  const pool = variables.pool;
  if (pool === null) {
    if (variables.loading) return { sections: [noticeSection("variables", L.variablesLoading)], nextEvent: null, footnote: L.openTabHint };
    if (variables.error !== null) return { sections: [noticeSection("variables", L.readFailed)], nextEvent: null, footnote: L.openTabHint };
    return { sections: [noticeSection("variables", L.variablesNotLoaded)], nextEvent: null, footnote: L.openTabHint };
  }
  const entries = pool.variables;
  const numbers = entries.filter((entry) => entry.kind === "number").length;
  const strings = entries.filter((entry) => entry.kind === "string").length;
  const invalid = entries.filter((entry) => entry.kind === "invalid").length;
  const issues = pool.issues.length + entries.reduce((sum, entry) => sum + entry.issues.length, 0);
  const rows: TabPreviewRow[] = [
    row("total", L.variableCount, String(entries.length)),
    row("numbers", L.variableNumbers, String(numbers)),
    row("strings", L.variableStrings, String(strings)),
    row("invalid", L.variableInvalid, String(invalid), invalid > 0 ? "warning" : "normal"),
    row("issues", L.variableIssues, String(issues), issues > 0 ? "warning" : "normal"),
  ];
  let notice: string | null = null;
  if (!pool.scan_complete) notice = L.scanIncomplete;
  else if (variables.loading) notice = L.loading;
  else if (variables.error !== null) notice = L.cachedSnapshot;
  else if (entries.length === 0) notice = L.variablesEmpty;
  return { sections: [section("variables", rows, null, notice)], nextEvent: null, footnote: L.openTabHint };
}

export function selectFileChangesPreview(input: TabPreviewInput): TabPreviewModel {
  const fileChanges = input.fileChanges;
  const summary = fileChanges.summary;
  if (summary === null) {
    const notice = fileChanges.summaryStatus === "error"
      ? L.fileChangesReadFailed
      : fileChanges.summaryStatus === "loading" || fileChanges.summaryStatus === "refreshing"
        ? L.loading
        : L.notLoaded;
    return { sections: [noticeSection("file-changes", notice)], nextEvent: null, footnote: L.openTabHint };
  }
  const rows: TabPreviewRow[] = [
    row("files", L.fileChangesFiles, String(summary.file_count)),
    row("directories", L.fileChangesDirectories, String(summary.directory_count)),
    row("operations", L.fileChangesOperations, String(summary.operation_count)),
    row(
      "last-operated",
      L.fileChangesLastOperatedAt,
      summary.last_operated_at === null ? L.fileChangesNone : new Date(summary.last_operated_at).toLocaleString(),
    ),
  ];
  let notice: string | null = null;
  if (fileChanges.summaryStatus === "error") notice = L.fileChangesReadFailed;
  else if (fileChanges.pageError !== null) notice = L.fileChangesPageFailed;
  else if (fileChanges.pageStale) notice = L.cachedSnapshot;
  else if (!fileChanges.pageLoaded) notice = L.fileChangesListNotLoaded;
  return { sections: [section("file-changes", rows, null, notice)], nextEvent: null, footnote: L.openTabHint };
}