import type { DownloadInfo, PlaylistEntry } from "./types";

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