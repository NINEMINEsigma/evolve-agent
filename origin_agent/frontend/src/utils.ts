import type { ChatMessage, DownloadInfo, PlaylistEntry, SubagentSession } from "./types";

export function formatTimeSec(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

export interface ParsedToolResult {
  content?: string;
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  audioUrl?: string;
  audioAutoplay?: boolean;
  playlist?: PlaylistEntry[];
  playlistAutoplay?: boolean;
}

export interface MessageResources {
  images: Array<{ id: string; src: string; alt: string }>;
  audios: Array<{ id: string; url: string; autoplay?: boolean }>;
  downloads: Array<{ id: string; url: string; filename: string; size?: number }>;
}

export function parseToolResult(raw: string, toolName?: string): ParsedToolResult {
  const prefix = toolName ? `✅ ${toolName} → ` : "";
  const fallbackLimit = toolName ? 2000 : raw.length;
  const messageLimit = toolName ? 200 : raw.length;

  try {
    const parsed = JSON.parse(raw);
    const message = typeof parsed.message === "string" ? parsed.message : "";
    const result: ParsedToolResult = {};

    if (parsed.markdown) {
      result.imageMarkdown = parsed.markdown;
      result.content = prefix + message.slice(0, messageLimit);
      return result;
    }

    if (parsed.download_url) {
      result.downloadInfo = {
        url: parsed.download_url,
        filename: parsed.filename || "download",
        description: parsed.description,
        size: parsed.size,
      };
      result.content = prefix + message.slice(0, messageLimit);
      return result;
    }

    if (parsed.audio_url) {
      result.audioUrl = parsed.audio_url;
      result.audioAutoplay = toolName ? parsed.autoplay === true : false;
      result.content = prefix + message.slice(0, messageLimit);
      return result;
    }

    if (parsed.playlist) {
      result.playlist = parsed.playlist;
      result.playlistAutoplay = toolName ? parsed.autoplay === true : false;
      result.content = prefix + message.slice(0, messageLimit);
      return result;
    }

    if (message) {
      result.content = prefix + message.slice(0, messageLimit);
      return result;
    }

    result.content = prefix + raw.slice(0, fallbackLimit);
    return result;
  } catch {
    return { content: prefix + raw.slice(0, fallbackLimit) };
  }
}

export interface MessageResourceSource {
  id: string;
  role: string;
  content: string | unknown;
  imageMarkdown?: string;
  audioUrl?: string;
  audioAutoplay?: boolean;
  downloadInfo?: DownloadInfo;
}

export function extractMessageResources(messages: MessageResourceSource[]): MessageResources {
  const images: MessageResources["images"] = [];
  const audios: MessageResources["audios"] = [];
  const downloads: MessageResources["downloads"] = [];
  const seen = new Set<string>();

  messages.forEach((m) => {
    if (m.imageMarkdown) {
      const match = m.imageMarkdown.match(/!\[(.*?)\]\(([^)]+)\)/);
      if (match) {
        const src = match[2];
        if (!seen.has(src)) {
          seen.add(src);
          images.push({ id: `${m.id}-img`, src, alt: match[1] || "" });
        }
      }
    }

    if (m.audioUrl && !seen.has(m.audioUrl)) {
      seen.add(m.audioUrl);
      audios.push({ id: `${m.id}-audio`, url: m.audioUrl, autoplay: m.audioAutoplay });
    }

    if (m.downloadInfo && !seen.has(m.downloadInfo.url)) {
      seen.add(m.downloadInfo.url);
      downloads.push({
        id: `${m.id}-dl`,
        url: m.downloadInfo.url,
        filename: m.downloadInfo.filename,
        size: m.downloadInfo.size,
      });
    }

    if (m.role === "agent" && typeof m.content === "string") {
      const imgMatches = m.content.matchAll(/!\[(.*?)\]\(([^)]+)\)/g);
      for (const match of imgMatches) {
        const src = match[2];
        if (!seen.has(src)) {
          seen.add(src);
          images.push({ id: `${m.id}-mdimg-${src.slice(-8)}`, src, alt: match[1] || "" });
        }
      }
    }
  });

  return { images, audios, downloads };
}

export function subagentFeedbackToChatMessages(session: SubagentSession): ChatMessage[] {
  const baseId = session.session_id;
  const messages: ChatMessage[] = [];

  session.feedback.forEach((msg, idx) => {
    const id = `${baseId}-msg-${idx}`;
    const role = (msg.role || "").toLowerCase();

    switch (role) {
      case "user":
        messages.push({ role: "user", content: msg.content || "", id });
        break;
      case "assistant":
        messages.push({
          role: "agent",
          content: msg.content || "",
          id,
          reasoningContent: msg.reasoning,
        });
        break;
      case "reasoning":
        messages.push({
          role: "agent",
          content: "",
          id,
          reasoningContent: msg.reasoning || msg.content,
        });
        break;
      case "tool_call": {
        const toolName = msg.tool_name || "";
        const argsStr = msg.tool_args ? `(${JSON.stringify(msg.tool_args)})` : "()";
        messages.push({
          role: "tool",
          content: `⚡ ${toolName}${argsStr}`,
          id,
          toolName,
          toolArgs: msg.tool_args,
        });
        break;
      }
      case "tool_result":
        messages.push({
          role: "tool",
          content: msg.content || "",
          id,
          toolName: msg.tool_name,
        });
        break;
      case "status":
      case "completed":
      case "terminated":
        messages.push({
          role: "system",
          content: msg.content || (role === "completed" ? "子会话已完成" : role === "terminated" ? "子会话已终止" : ""),
          id,
        });
        break;
      case "approval_pending": {
        const toolName = msg.tool_name || "";
        const argsStr = msg.tool_args ? `\n${JSON.stringify(msg.tool_args, null, 2)}` : "";
        messages.push({
          role: "system",
          content: `⏸ 待审批: ${toolName}${argsStr}`,
          id,
          toolName,
          toolArgs: msg.tool_args,
        });
        break;
      }
      case "approval_decision": {
        const toolName = msg.tool_name ? `${msg.tool_name}: ` : "";
        messages.push({
          role: "system",
          content: `${toolName}${msg.content}`,
          id,
        });
        break;
      }
      default:
        messages.push({ role: "system", content: msg.content || "", id });
    }
  });

  session.pending_approvals.forEach((pa, idx) => {
    messages.push({
      role: "tool",
      content: `⏸ 待审批: ${pa.tool_name}\n${JSON.stringify(pa.arguments, null, 2)}`,
      id: `${baseId}-pending-${idx}`,
      toolName: pa.tool_name,
      toolArgs: pa.arguments,
    });
  });

  return messages;
}

export function generateUUID(): string {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
