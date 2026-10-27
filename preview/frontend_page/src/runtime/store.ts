import type {
  FileSnapshot, SessionInfo, MessageContent, LlmProfile, DynamicSandboxSpaceWithAvailability,
  TrashEntry, FileLock, ApprovalProfileState, ModalityType,
} from "@origin/types";
import type { HistoryContentRowDto, HistorySkeletonResponseDto, HistoryPageResponseDto, HistoryResourcesResponseDto } from "@origin/features/chat/types";
import type { SessionFileChangesSummaryDto } from "@origin/features/sessionFileChanges/types";
import { getTextVersion } from "@origin/services/agentspaceApi";
import { COLLOQUY_SID } from "@origin/constants/session";
import type { PreviewFile, PreviewSceneId, PreviewSession } from "../types";
import { createSeedSessions } from "../data/sessions";
import { createCatalog } from "../data/catalog";
import { createSeedFiles } from "../data/files";
import { DEMO_ASSETS, PREVIEW, PREVIEW_MEDIA_URLS } from "../constants";
import { PreviewHttpError } from "../transport/contracts";
import labels from "../content/zh-CN.json";

interface StoredTrash { entry: TrashEntry; files: PreviewFile[] }
export class PreviewStore {
  readonly sessions: Map<string, PreviewSession>;
  readonly seedIds: ReadonlySet<string>;
  readonly files: Map<string, PreviewFile>;
  readonly trash = new Map<string, StoredTrash>();
  readonly drafts = new Map<string, { streamId: string; author: string; content: string; reasoning: string }>();
  readonly locks: FileLock[] = [];
  profiles: LlmProfile[];
  spaces: DynamicSandboxSpaceWithAvailability[];
  references: Record<"approval" | "metadata" | "toolchain" | ModalityType, string | null>;
  maxToolTurns: number | null = null;
  private sequence = 0;
  private readonly emptyTemplate: PreviewSession;
  constructor(readonly scene: PreviewSceneId) {
    const sessions = createSeedSessions();
    const empty = sessions.find((session) => session.info.id === PREVIEW.emptySession);
    if (!empty) throw new Error("Empty session seed is missing");
    this.emptyTemplate = structuredClone(empty);
    this.sessions = new Map(sessions.map((session) => [session.info.id, session]));
    this.seedIds = new Set(this.sessions.keys());
    PREVIEW_MEDIA_URLS.clear();
    for (const session of sessions) for (const item of session.media) {
      if (item.media_type !== "image") continue;
      PREVIEW_MEDIA_URLS.set(`${session.info.id}/${item.media_id}`, item.source_path?.endsWith("diagram.svg") ? DEMO_ASSETS.diagram : DEMO_ASSETS.cover);
    }
    this.files = new Map(createSeedFiles().map((file) => [file.path, file]));
    this.locks.push({ path: "reports/locked.md", recursive: false, owners: [{ owner_id: "preview-lock",
      session_id: PREVIEW.mainSession, character_name: "Research", round_id: "preview-round" }] });
    const catalog = createCatalog(); this.profiles = catalog.profiles; this.spaces = catalog.spaces;
    this.references = { approval: this.profiles[0]?.name ?? null, metadata: this.profiles[0]?.name ?? null,
      toolchain: this.profiles[0]?.name ?? null, image: this.profiles[1]?.name ?? null,
      audio: this.profiles[1]?.name ?? null, video: this.profiles[1]?.name ?? null };
  }
  nextId(prefix: string): string { return `${prefix}-${++this.sequence}`; }
  session(id: string): PreviewSession {
    const session = this.sessions.get(id);
    if (!session) throw new PreviewHttpError(404, "Preview session does not exist");
    return session;
  }
  writable(id: string): PreviewSession {
    const session = this.session(id);
    if (session.info.status === "archived") throw new PreviewHttpError(403, "Archived preview session is read-only");
    return session;
  }
  idle(id: string): PreviewSession {
    const session = this.writable(id);
    if (session.activity) throw new PreviewHttpError(409, "Preview response is still processing");
    return session;
  }
  listSessions(): SessionInfo[] {
    return [...this.sessions.values()].filter((session) => session.info.id !== COLLOQUY_SID).map((session) => structuredClone(session.info));
  }
  createSession(sources: string[] = []): PreviewSession {
    for (const id of sources) if (this.session(id).info.status !== "archived") throw new PreviewHttpError(409, "Only archived sources can be continued");
    const empty = structuredClone(this.emptyTemplate);
    const id = this.nextId("preview-session");
    empty.info = { id, title: sources.length ? labels.script.title : "", status: "active", created_at: PREVIEW.epochMs / 1000, parents: sources };
    empty.variables.session_id = id;
    this.sessions.set(id, empty);
    return empty;
  }
  appendMessage(id: string, role: "user" | "assistant" | "system", content: MessageContent, characterName: string): HistoryContentRowDto {
    const session = this.session(id);
    const index = session.historyCount++;
    const row: HistoryContentRowDto = {
      row_id: `history:${index}:message`, history_index: index, row_kind: "message", role,
      character_name: characterName, is_system_status: false, content,
      content_excerpt: role === "user" && typeof content === "string" ? content.slice(0, 80) : null,
    };
    session.rows.push(row);
    this.syncMessageMedia(id, row);
    return row;
  }
  syncMessageMedia(id: string, row: HistoryContentRowDto): void {
    const session = this.session(id);
    const previous = session.media.filter((item) => item.history_index === row.history_index);
    session.media = session.media.filter((item) => item.history_index !== row.history_index);
    const blocks = Array.isArray(row.content) ? row.content : [];
    blocks.forEach((block, index) => {
      if (block.type === "text") return;
      const type = block.type === "image_url" ? "image" : block.type === "input_audio" ? "audio" : "video";
      const url = block.type === "image_url" ? block.image_url.url : block.type === "input_audio"
        ? `data:audio/${block.input_audio.format};base64,${block.input_audio.data}` : block.video_url.url;
      const available = url.startsWith("data:image/") || url.startsWith("data:audio/") || url.startsWith("data:video/")
        || url.startsWith(`blob:${location.origin}/`) || Object.values(DEMO_ASSETS).some((asset) => url === asset);
      const old = previous.find((item) => item.block_index === index && item.media_type === type);
      const mediaId = old?.media_id ?? this.nextId("preview-media");
      PREVIEW_MEDIA_URLS.set(`${id}/${mediaId}`, available ? url : "");
      session.media.push({ media_id: mediaId, history_index: row.history_index, block_index: index, media_type: type,
        role: row.role === "assistant" ? "assistant" : row.role === "system" ? "system" : "user",
        character_name: row.character_name ?? null, source_path: old?.source_path ?? null, tool_call_id: null,
        send_multimodal: old?.send_multimodal ?? true, has_forward_description: old?.has_forward_description ?? false,
        mime_type: url.startsWith("data:") ? url.slice(5, url.indexOf(";")) : type === "image" ? "image/svg+xml" : null,
        inline_payload_chars: url.startsWith("data:") ? url.slice(url.indexOf(",") + 1).length : null, preview_available: available });
    });
    const retained = new Set(session.media.map((item) => item.media_id));
    for (const item of previous) if (!retained.has(item.media_id)) PREVIEW_MEDIA_URLS.delete(`${id}/${item.media_id}`);
  }
  appendTool(id: string, toolId: string, result: string): HistoryContentRowDto {
    const session = this.session(id);
    const index = session.historyCount; session.historyCount += 2;
    const row: HistoryContentRowDto = {
      row_id: `history:${index}:tool:0`, history_index: index, row_kind: "tool_card", role: "assistant",
      character_name: "main-agent", tool_index: 0, tool_call_id: toolId, is_system_status: false, content: "",
      tool_card: { tool_call_id: toolId, tool_name: "Write", request_args: { path: "ws:reports/brief.md", content: result },
        status: "succeeded", result_content: result, result_history_index: index + 1, is_error: false },
    };
    session.rows.push(row);
    session.revision += 1;
    const changed = session.changes.find((item) => item.path === "ws:reports/brief.md");
    if (changed) {
      changed.operation_count += 1; changed.last_revision = session.revision;
      changed.last_operation = "modify"; changed.last_tool_name = "Write"; changed.last_operated_at = PREVIEW.timestamp;
    } else session.changes.push({ path: "ws:reports/brief.md", kind: "file", display_state: "created", created_by_session: true,
      operation_count: 1, last_revision: session.revision, last_operation: "create", last_tool_name: "Write",
      last_operated_at: PREVIEW.timestamp, actors: [{ session_id: id, character_name: "main-agent" }], source_path: null, destination_path: null });
    return row;
  }
  skeleton(id: string, start: number): HistorySkeletonResponseDto {
    const session = this.session(id);
    return { session_id: id, start_index: start, history_count: session.historyCount, row_count: session.rows.length,
      rows: session.rows.filter((row) => row.history_index >= start).map((row) => ({
        row_id: row.row_id, history_index: row.history_index, row_kind: row.row_kind, role: row.role,
        character_name: row.character_name, tool_index: row.tool_index, tool_call_id: row.tool_call_id,
        is_system_status: row.is_system_status, content_excerpt: row.content_excerpt,
      })) };
  }
  page(id: string, start: number, limit: number): HistoryPageResponseDto {
    const session = this.session(id);
    return { session_id: id, start_index: start, end_index: Math.min(start + limit, session.historyCount), history_count: session.historyCount,
      rows: structuredClone(session.rows.filter((row) => row.history_index >= start && row.history_index < start + limit)) };
  }
  resources(id: string): HistoryResourcesResponseDto {
    const session = this.session(id);
    const hasContent = session.media.length > 0;
    return { session_id: id, history_count: session.historyCount,
      images: session.media.filter((item) => item.media_type === "image" && item.preview_available).map((item) => ({
        resource_id: item.media_id, url: PREVIEW_MEDIA_URLS.get(`${id}/${item.media_id}`) ?? DEMO_ASSETS.cover,
        alt: item.source_path ?? labels.ui.exportTitle,
      })),
      downloads: hasContent ? [{ resource_id: "preview-report", url: DEMO_ASSETS.site, filename: "preview-report.html", size: 2048 }] : [] };
  }
  summary(id: string): SessionFileChangesSummaryDto {
    const session = this.session(id);
    return { session_id: id, revision: session.revision,
      file_count: session.changes.filter((item) => item.kind === "file").length,
      directory_count: session.changes.filter((item) => item.kind === "directory").length,
      operation_count: session.changes.reduce((sum, item) => sum + item.operation_count, 0),
      last_operated_at: session.changes.length ? PREVIEW.timestamp : null };
  }
  trim(id: string, keep: number): void {
    const session = this.session(id);
    session.rows = session.rows.filter((row) => row.history_index < keep && (!row.tool_card || (row.tool_card.result_history_index ?? keep) < keep));
    session.historyCount = keep;
    session.media = session.media.filter((item) => item.history_index < keep);
  }
  deleteAt(id: string, index: number): void {
    const session = this.idle(id);
    const row = session.rows.find((item) => item.history_index === index || item.tool_card?.result_history_index === index);
    if (!row) throw new PreviewHttpError(404, "Message does not exist");
    const removed = [row.history_index];
    if (row.tool_card?.result_history_index != null) removed.push(row.tool_card.result_history_index);
    session.rows = session.rows.filter((item) => item !== row);
    session.media = session.media.filter((item) => !removed.includes(item.history_index));
    for (const item of session.rows) {
      const shift = removed.filter((value) => value < item.history_index).length;
      item.history_index -= shift;
      item.row_id = item.row_kind === "tool_card" ? `history:${item.history_index}:tool:0` : `history:${item.history_index}:message`;
      if (item.tool_card?.result_history_index != null) item.tool_card.result_history_index -= removed.filter((value) => value < item.tool_card!.result_history_index!).length;
    }
    for (const item of session.media) item.history_index -= removed.filter((value) => value < item.history_index).length;
    session.historyCount -= removed.length;
  }
  profileState(name: string | null): ApprovalProfileState {
    const profile = this.profiles.find((item) => item.name === name);
    return { profile_name: name, model: profile?.model ?? null, available: !!profile };
  }
  filePath(input: string): string {
    const normalized = input.replace(/^ws:/, "");
    if (normalized.includes("\\") || normalized.includes(":") || normalized.startsWith("/") || normalized.split("/").includes("..")) throw new PreviewHttpError(422, "Invalid virtual path");
    return normalized.replace(/\/$/, "");
  }
  async snapshot(path: string): Promise<FileSnapshot> {
    const item = this.files.get(this.filePath(path));
    if (!item || item.kind !== "file") throw new PreviewHttpError(404, "Virtual file does not exist");
    return { path: item.path, content: item.content, version: await getTextVersion(item.content),
      size: new TextEncoder().encode(item.content).length, modified_ns: PREVIEW.epochMs * 1000000 };
  }
}
export function createPreviewStore(scene: PreviewSceneId): PreviewStore { return new PreviewStore(scene); }
