import { COLLOQUY_SID } from "@origin/constants/session";
import type { HistoryContentRowDto } from "@origin/features/chat/types";
import type { MessageContent } from "@origin/types";
import { DEMO_ASSETS, PREVIEW } from "../constants";
import content from "../content/zh-CN.json";
import type { PreviewSession } from "../types";

function createSession(id: string, title: string): PreviewSession {
  return {
    info: {
      id, title, status: "active", loop_type: "parent", pinned: false,
      created_at: PREVIEW.epochMs / 1000 - 3600,
      last_activity_at: PREVIEW.epochMs / 1000,
      parents: [], parent: null, continuation: null, tags: [...content.sessions.tags],
    },
    rows: [], historyCount: 0, profileName: PREVIEW.defaultProfile,
    approvalMode: "manual", agents: [], activity: null, tokenUsage: 0, contextTokens: 0,
    media: [], changes: [], revision: 0,
    variables: {
      session_id: id, directory_path: `ws:sessions/${id}/variables`,
      root_exists: false, scan_complete: true, version: PREVIEW.version,
      variables: [], issues: [],
    },
    shells: [], cronTasks: [], subagents: {}, taskProgress: {}, endpoints: [],
    confirm: null, ask: null,
  };
}

function addMessage(
  session: PreviewSession,
  role: "user" | "assistant",
  body: MessageContent,
  characterName = role === "user" ? "end-user" : "main-agent",
  reasoning?: string,
): number {
  const index = session.historyCount++;
  const row: HistoryContentRowDto = {
    row_id: `history:${index}:message`, history_index: index, row_kind: "message", role,
    character_name: characterName, is_system_status: false, content: body,
    content_excerpt: typeof body === "string" ? body.slice(0, 80) : content.sessions.userEvidence,
  };
  if (reasoning !== undefined) row.reasoning_content = reasoning;
  if (role === "assistant") {
    row.metrics = {
      reasoning_duration_ms: reasoning ? 1260 : 0,
      content_duration_ms: 4800, completion_tokens: 384, tokens_per_second: 80,
    };
  }
  session.rows.push(row);
  return index;
}

function addTool(
  session: PreviewSession,
  name: string,
  args: Record<string, unknown>,
  result: string | null,
): void {
  const requestIndex = session.historyCount++;
  // 工具结果占独立 History 索引，但投影只保留聚合工具卡片。
  const resultIndex = result === null ? null : session.historyCount++;
  const toolCallId = `${session.info.id}-tool-${requestIndex}`;
  session.rows.push({
    row_id: `history:${requestIndex}:tool:0`, history_index: requestIndex,
    row_kind: "tool_card", role: "assistant", character_name: "main-agent",
    tool_index: 0, tool_call_id: toolCallId, is_system_status: false, content: "",
    tool_card: {
      tool_call_id: toolCallId, tool_name: name, request_args: args,
      request_args_raw: JSON.stringify(args), status: result === null ? "running" : "succeeded",
      result_content: result, result_history_index: resultIndex, is_error: false,
      tool_call_meta: result === null ? null : {
        application_time: "2026-10-27 10:30:00.000", application_time_ms: PREVIEW.epochMs,
        approval_duration_ms: 0, invocation_start_offset_ms: 0,
        invocation_duration_ms: 184, end_time_offset_ms: 184,
      },
    },
  });
}

function addCover(session: PreviewSession): void {
  const historyIndex = addMessage(session, "user", [
    { type: "text", text: content.sessions.userEvidence },
    { type: "image_url", image_url: { url: DEMO_ASSETS.cover } },
  ]);
  session.media.push({
    media_id: `${session.info.id}-cover`, history_index: historyIndex, block_index: 1,
    media_type: "image", role: "user", character_name: "end-user",
    source_path: "ws:assets/cover.svg", tool_call_id: null, send_multimodal: true,
    has_forward_description: true, mime_type: "image/svg+xml", inline_payload_chars: null,
    preview_available: true,
  });
}

function addResources(session: PreviewSession): void {
  const id = session.info.id;
  session.tokenUsage = 28460;
  session.contextTokens = 12680;
  session.changes = [
    {
      path: "ws:reports/brief.md", kind: "file", display_state: "created",
      created_by_session: true, operation_count: 2, last_operation: "modify",
      last_tool_name: "PatchEdit", actors: [{ session_id: id, character_name: "main-agent" }],
      last_operated_at: PREVIEW.timestamp, last_revision: 4,
      source_path: null, destination_path: null,
    },
    {
      path: "ws:reports/checklist.md", kind: "file", display_state: "created",
      created_by_session: true, operation_count: 1, last_operation: "create",
      last_tool_name: "Write", actors: [{ session_id: id, character_name: "main-agent" }],
      last_operated_at: PREVIEW.timestamp, last_revision: 3,
      source_path: null, destination_path: null,
    },
    {
      path: "ws:reports/review.md", kind: "file", display_state: "modified",
      created_by_session: false, operation_count: 1, last_operation: "modify",
      last_tool_name: "PatchEdit", actors: [{ session_id: id, character_name: "Research" }],
      last_operated_at: PREVIEW.timestamp, last_revision: 2,
      source_path: null, destination_path: null,
    },
  ];
  session.revision = 4;
  const directoryPath = session.variables.directory_path;
  session.variables.root_exists = true;
  session.variables.variables = [
    {
      id: "delivery/progress.json", path: `${directoryPath}/delivery/progress.json`,
      metadata_path: `${directoryPath}/delivery/progress.json.meta`, group: "delivery",
      kind: "number", value: 1, raw_value: "1", raw_metadata: {
        label: content.variables.progress, description: content.variables.progressDescription,
        min: "0", max: "1", percent: "true", display: "bar",
      },
      metadata: {
        label: content.variables.progress, description: content.variables.progressDescription,
        min: 0, max: 1, integer: false, percent: true, display: "bar",
      }, issues: [],
    },
    {
      id: "research/coverage.json", path: `${directoryPath}/research/coverage.json`,
      metadata_path: `${directoryPath}/research/coverage.json.meta`, group: "research",
      kind: "number", value: 0.84, raw_value: "0.84", raw_metadata: {
        label: content.variables.evidence, description: content.variables.evidenceDescription,
        min: "0", max: "1", percent: "true", display: "gauge",
      },
      metadata: {
        label: content.variables.evidence, description: content.variables.evidenceDescription,
        min: 0, max: 1, integer: false, percent: true, display: "gauge",
      }, issues: [],
    },
    {
      id: "delivery/items.json", path: `${directoryPath}/delivery/items.json`,
      metadata_path: `${directoryPath}/delivery/items.json.meta`, group: "delivery",
      kind: "number", value: 3, raw_value: "3", raw_metadata: {
        label: content.variables.items, description: content.variables.itemsDescription,
        min: "0", max: "3", integer: "true", display: "number",
      },
      metadata: {
        label: content.variables.items, description: content.variables.itemsDescription,
        min: 0, max: 3, integer: true, percent: false, display: "number",
      }, issues: [],
    },
    {
      id: "delivery/phase.json", path: `${directoryPath}/delivery/phase.json`,
      metadata_path: `${directoryPath}/delivery/phase.json.meta`, group: "delivery",
      kind: "string", value: content.variables.phaseValue,
      raw_value: JSON.stringify(content.variables.phaseValue), raw_metadata: {
        label: content.variables.phase, description: content.variables.phaseDescription,
      },
      metadata: {
        label: content.variables.phase, description: content.variables.phaseDescription,
        min: null, max: null, integer: false, percent: false, display: "auto",
      }, issues: [],
    },
  ];
  session.shells = [{
    shell_id: `${id}-shell`, pid: null, session_id: id, character_name: "main-agent",
    shell_type: "PowerShell", cwd: "ws:reports", started_at: PREVIEW.epochMs / 1000 - 1800,
    last_activity_at: PREVIEW.epochMs / 1000 - 600, running: false,
    termination: "natural", exit_code: 0,
    cleanup: { complete: true, pending_resources: [], warnings: [] },
  }];
  session.cronTasks = [{
    task_id: `${id}-review`, session_id: id, name: content.resources.cronName,
    schedule_type: "interval", schedule_value: "86400", next_run: null,
    run_count: 2, max_runs: 3, should_schedule: false,
    log_path: "ws:reports/review.log", is_wait: false,
  }];
  const researchId = `${id}-research`;
  const designId = `${id}-design`;
  session.subagents = {
    [researchId]: {
      session_id: researchId, name: "Research", status: "completed", interactive: false,
      feedback: [
        { role: "user", character_name: "main-agent", content: content.characters.researchTask },
        { role: "assistant", character_name: "Research", content: content.characters.researchFeedback },
      ], pending_approvals: [],
    },
    [designId]: {
      session_id: designId, name: "Design", status: "completed", interactive: false,
      feedback: [
        { role: "user", character_name: "main-agent", content: content.characters.designTask },
        { role: "assistant", character_name: "Design", content: content.characters.designFeedback },
      ], pending_approvals: [],
    },
  };
  session.taskProgress = {
    [`${id}-delivery`]: {
      task_id: `${id}-delivery`, label: content.resources.taskLabel,
      current: 3, total: 3, percent: 100, status: content.resources.completed,
    },
  };
  session.endpoints = [{
    name: content.resources.endpointName, url: DEMO_ASSETS.site,
    agent_name: "main-agent", created_at: PREVIEW.epochMs / 1000 - 300,
  }];
}

function createShowcase(): PreviewSession {
  const session = createSession(PREVIEW.mainSession, content.sessions.mainTitle);
  session.info.pinned = true;
  session.info.parents = [PREVIEW.archivedSession];
  session.info.parent = PREVIEW.archivedSession;
  addMessage(session, "user", content.sessions.userBrief);
  addMessage(session, "assistant", content.sessions.outline);
  addCover(session);
  addTool(session, "Read", { path: "ws:notes/audience.md" }, content.sessions.toolReadResult);
  addTool(session, "Write", {
    path: "ws:reports/brief.md", content: content.files.brief,
  }, content.sessions.toolWriteResult);
  addMessage(session, "user", content.sessions.userRefine);
  addMessage(session, "assistant", content.sessions.final, "main-agent", content.sessions.reasoning);
  addResources(session);
  return session;
}

function createMulti(): PreviewSession {
  const session = createSession(PREVIEW.multiSession, content.sessions.multiTitle);
  session.info.loop_type = "multi";
  session.agents = ["main-agent", "Design", "Research"];
  addMessage(session, "user", content.sessions.multiUser);
  addCover(session);
  addMessage(session, "assistant", content.sessions.multiProduct);
  addMessage(session, "assistant", content.sessions.multiDesign, "Design");
  addMessage(session, "assistant", content.sessions.multiResearch, "Research");
  addTool(session, "Write", {
    path: "ws:reports/review.md", content: content.files.review,
  }, content.sessions.toolWriteResult);
  addMessage(session, "assistant", content.sessions.multiConclusion);
  addResources(session);
  return session;
}

function createApproval(): PreviewSession {
  const session = createSession(PREVIEW.approvalSession, content.sessions.approvalTitle);
  addMessage(session, "user", content.sessions.approvalUser);
  addCover(session);
  addMessage(session, "assistant", content.sessions.approvalReply);
  addTool(session, "Delete", { path: content.approval.path }, null);
  session.confirm = {
    request_id: "preview-confirm-cleanup", content: content.approval.content,
    reason: content.approval.reason, tool: "Delete", danger_level: "dangerous",
    args: { path: content.approval.path },
  };
  session.activity = {
    activity_id: "preview-approval-activity", revision: 1, source: "user_message",
    phase: "waiting_approval", character_name: "main-agent",
  };
  addResources(session);
  return session;
}

function createQuestion(): PreviewSession {
  const session = createSession(PREVIEW.questionSession, content.sessions.questionTitle);
  addMessage(session, "user", content.sessions.questionUser);
  addCover(session);
  addMessage(session, "assistant", content.sessions.questionReply);
  session.ask = {
    request_id: "preview-ask-release",
    questions: [
      {
        question: content.question.audience, detail: content.question.audienceDetail,
        options: [
          { label: content.question.creator, value: "creator" },
          { label: content.question.team, value: "team" },
          { label: content.question.researcher, value: "researcher" },
        ], multi_select: false,
      },
      {
        question: content.question.action, detail: content.question.actionDetail,
        options: [
          { label: content.question.learn, value: "learn" },
          { label: content.question.start, value: "start" },
        ], multi_select: false,
      },
      {
        question: content.question.tone, detail: content.question.toneDetail,
        options: [
          { label: content.question.clear, value: "clear" },
          { label: content.question.calm, value: "calm" },
          { label: content.question.warm, value: "warm" },
        ], multi_select: true,
      },
    ],
  };
  session.activity = {
    activity_id: "preview-question-activity", revision: 1, source: "user_message",
    phase: "waiting_tool", character_name: "main-agent",
  };
  addResources(session);
  return session;
}

function createArchived(): PreviewSession {
  const session = createSession(PREVIEW.archivedSession, content.sessions.archivedTitle);
  session.info.status = "archived";
  session.info.tags = [...content.sessions.archivedTags];
  session.info.continuation = PREVIEW.mainSession;
  session.info.created_at = PREVIEW.epochMs / 1000 - 86400;
  session.info.last_activity_at = PREVIEW.epochMs / 1000 - 7200;
  addMessage(session, "user", content.sessions.archivedUser);
  addMessage(session, "assistant", content.sessions.archivedReply);
  session.tokenUsage = 6420;
  session.contextTokens = 3180;
  return session;
}

export function createSeedSessions(): PreviewSession[] {
  const empty = createSession(PREVIEW.emptySession, content.sessions.emptyTitle);
  empty.info.tags = [];
  const colloquy = createSession(COLLOQUY_SID, content.sessions.colloquyTitle);
  colloquy.info.loop_type = "colloquy";
  colloquy.info.tags = [];
  addMessage(colloquy, "user", content.sessions.colloquyUser);
  addMessage(colloquy, "assistant", content.sessions.colloquyReply);
  colloquy.tokenUsage = 860;
  colloquy.contextTokens = 420;
  return [createShowcase(), empty, createMulti(), createApproval(), createQuestion(), createArchived(), colloquy];
}
