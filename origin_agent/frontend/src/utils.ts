import type { ChatMessage, ContentBlock, DownloadInfo, PendingImage, PendingAudio, PendingVideo, SubagentSession } from "./types";
import { WS_IN } from "./constants/ws";

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
  isError?: boolean;
}

export interface MessageResources {
  images: Array<{ id: string; src: string; alt: string }>;
  downloads: Array<{ id: string; url: string; filename: string; size?: number }>;
}

export function parseToolResult(raw: string, _toolName?: string): ParsedToolResult {
  try {
    const parsed = JSON.parse(raw);
    const isError = !!parsed.error;
    const result: ParsedToolResult = { isError };

    // 提取特殊字段（由前端独立组件渲染）
    if (parsed.markdown) result.imageMarkdown = parsed.markdown;
    if (parsed.download_url) {
      result.downloadInfo = {
        url: parsed.download_url,
        filename: parsed.filename || "download",
        description: parsed.description,
        size: parsed.size,
      };
    }

    // 移除所有下划线开头的字段（_meta, _image, _note, _parse_failed 等）
    const cleaned: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (!k.startsWith("_")) cleaned[k] = v;
    }

    // content 始终为完整 JSON（pretty-print）
    result.content = JSON.stringify(cleaned, null, 2);
    return result;
  } catch {
    return { content: raw, isError: false };
  }
}

export interface MessageResourceSource {
  id: string;
  role: string;
  content: string | unknown;
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
}

export function extractMessageResources(messages: MessageResourceSource[]): MessageResources {
  const images: MessageResources["images"] = [];
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

    if (m.downloadInfo && !seen.has(m.downloadInfo.url)) {
      seen.add(m.downloadInfo.url);
      downloads.push({
        id: `${m.id}-dl`,
        url: m.downloadInfo.url,
        filename: m.downloadInfo.filename,
        size: m.downloadInfo.size,
      });
    }

    if (m.role === "assistant" && typeof m.content === "string") {
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

  return { images, downloads };
}

export function subagentFeedbackToChatMessages(session: SubagentSession): ChatMessage[] {
  const baseId = session.session_id;
  const messages: ChatMessage[] = [];

  session.feedback.forEach((msg, idx) => {
    const id = `${baseId}-msg-${idx}`;
    const role = (msg.role || "").toLowerCase();

    switch (role) {
      case "user":
        messages.push({ role: "user", content: msg.content || "", id, characterName: msg.character_name });
        break;
      case "assistant":
        messages.push({
          role: "assistant",
          content: msg.content || "",
          id,
          reasoningContent: msg.reasoning,
          characterName: msg.character_name,
        });
        break;
      case "reasoning":
        messages.push({
          role: "assistant",
          content: "",
          id,
          reasoningContent: msg.reasoning || msg.content,
          characterName: msg.character_name,
        });
        break;
      case WS_IN.TOOL_CALL: {
        const toolName = msg.tool_name || "";
        const argsStr = msg.tool_args ? `(${JSON.stringify(msg.tool_args)})` : "()";
        messages.push({
          role: "tool",
          content: `${msg.emoji || "⚡"} ${toolName}${argsStr}`,
          id,
          toolName,
          toolArgs: msg.tool_args,
          emoji: msg.emoji,
        });
        break;
      }
      case WS_IN.TOOL_RESULT:
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

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── 多模态内容转换工具 ──────────────────────────────────────

/** 将 ContentBlock[] 转换为 RichInput 可用的 HTML，含内联图片/音频/视频 span。 */
export function contentBlocksToHtml(blocks: ContentBlock[], images: PendingImage[], audios: PendingAudio[], videos: PendingVideo[]): string {
  const imageMap = new Map(images.map((img) => [img.id, img]));
  const audioMap = new Map(audios.map((au) => [au.id, au]));
  const videoMap = new Map(videos.map((vd) => [vd.id, vd]));
  let html = "";
  for (const block of blocks) {
    if (block.type === "text") {
      html += escapeHtml(block.text).replace(/\n/g, "<br/>");
    } else if (block.type === "image_url") {
      // 查找匹配的 PendingImage 以获取 id
      const entry = Array.from(imageMap.entries()).find(([, img]) => img.dataUrl === block.image_url.url);
      const id = entry ? entry[0] : generateUUID();
      html += `<span class="input-inline-image" contenteditable="false" data-image-id="${id}"><img src="${block.image_url.url}" alt="" /><button type="button" class="input-inline-remove">x</button></span>`;
    } else if (block.type === "input_audio") {
      // 兼容两种 data：裸 base64（前端提取）或 data URL（后端 as_object 输出）
      const dataUrl = block.input_audio.data.startsWith("data:")
        ? block.input_audio.data
        : `data:audio/${block.input_audio.format};base64,${block.input_audio.data}`;
      const entry = Array.from(audioMap.entries()).find(([, au]) => au.dataUrl === dataUrl);
      const id = entry ? entry[0] : generateUUID();
      html += `<span class="input-inline-audio" contenteditable="false" data-audio-id="${id}" data-audio-src="${dataUrl}"><audio src="${dataUrl}" controls></audio><button type="button" class="input-inline-remove">x</button></span>`;
    } else if (block.type === "video_url") {
      const videoUrl = block.video_url.url;
      const entry = Array.from(videoMap.entries()).find(([, vd]) => vd.dataUrl === videoUrl);
      const id = entry ? entry[0] : generateUUID();
      html += `<span class="input-inline-video" contenteditable="false" data-video-id="${id}" data-video-src="${videoUrl}"><video src="${videoUrl}" controls></video><button type="button" class="input-inline-remove">x</button></span>`;
    }
  }
  return html;
}

/** 从 RichInput 的 DOM 中按遍历顺序提取 ContentBlock[]。 */
export function extractContentBlocks(el: HTMLDivElement | null, images: PendingImage[], audios: PendingAudio[], videos: PendingVideo[]): ContentBlock[] {
  if (!el) return [];
  const blocks: ContentBlock[] = [];
  const imageMap = new Map(images.map((img) => [img.id, img]));
  const audioMap = new Map(audios.map((au) => [au.id, au]));
  const videoMap = new Map(videos.map((vd) => [vd.id, vd]));

  const imageNodes = el.querySelectorAll<HTMLSpanElement>(".input-inline-image");
  const audioNodes = el.querySelectorAll<HTMLSpanElement>(".input-inline-audio");
  const videoNodes = el.querySelectorAll<HTMLSpanElement>(".input-inline-video");
  if (imageNodes.length === 0 && audioNodes.length === 0 && videoNodes.length === 0) {
    const text = (el.innerText || "").replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
    if (text) blocks.push({ type: "text", text });
    return blocks;
  }

  const mediaPositions = new Map<Node, { type: "image" | "audio" | "video"; data: PendingImage | PendingAudio | PendingVideo }>();
  imageNodes.forEach((node) => {
    const id = node.dataset.imageId;
    const img = id ? imageMap.get(id) : undefined;
    if (img) mediaPositions.set(node, { type: "image", data: img });
  });
  audioNodes.forEach((node) => {
    const id = node.dataset.audioId;
    const au = id ? audioMap.get(id) : undefined;
    if (au) {
      mediaPositions.set(node, { type: "audio", data: au });
    } else {
      // Fallback: 从 DOM 中的 <audio> src 属性直接提取，不依赖 pendingAudios state
      const audioEl = node.querySelector("audio");
      const dataUrl = audioEl?.src || "";
      if (dataUrl.startsWith("data:audio/")) {
        // 支持带 codec 的格式，如 data:audio/webm;codecs=opus;base64,...
        const formatMatch = dataUrl.match(/^data:audio\/([^;]+)(?:;[^;]*)*;base64,/);
        const format = formatMatch ? (formatMatch[1] === "mpeg" ? "mp3" : formatMatch[1]) : "wav";
        mediaPositions.set(node, {
          type: "audio",
          data: { id: id || generateUUID(), file: new File([], ""), dataUrl, format } as PendingAudio,
        });
      }
    }
  });
  videoNodes.forEach((node) => {
    const id = node.dataset.videoId;
    const vd = id ? videoMap.get(id) : undefined;
    if (vd) {
      mediaPositions.set(node, { type: "video", data: vd });
    } else {
      // Fallback: 从 DOM 中的 <video> src 属性直接提取
      const videoEl = node.querySelector("video");
      const dataUrl = videoEl?.src || "";
      if (dataUrl.startsWith("data:video/")) {
        mediaPositions.set(node, {
          type: "video",
          data: { id: id || generateUUID(), file: new File([], ""), dataUrl } as PendingVideo,
        });
      }
    }
  });

  let currentText = "";
  const flushText = () => {
    const cleaned = currentText.replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
    if (cleaned) blocks.push({ type: "text", text: cleaned });
    currentText = "";
  };

  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      currentText += node.textContent || "";
      return;
    }
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      if (el.classList?.contains("input-mention-chip")) {
        currentText += el.textContent || "";
        return;
      }
      // 直接从 DOM 提取音频，不依赖 mediaPositions map 或 data 属性
      if (el.classList?.contains("input-inline-audio")) {
        flushText();
        const audioEl = el.querySelector("audio");
        const src = audioEl?.getAttribute("src") || "";
        // 支持带 codec 的格式，如 data:audio/webm;codecs=opus;base64,...
        const match = src.match(/^data:audio\/([^;]+)(?:;[^;]*)*;base64,(.+)$/);
        if (match) {
          const mimeFmt = match[1];
          const format = mimeFmt === "mpeg" ? "mp3" : mimeFmt;
          blocks.push({ type: "input_audio", input_audio: { data: match[2], format } });
        }
        return;
      }
      // 直接从 DOM 提取视频，不依赖 mediaPositions map 或 data 属性
      if (el.classList?.contains("input-inline-video")) {
        flushText();
        const videoEl = el.querySelector("video");
        const src = videoEl?.getAttribute("src") || "";
        const match = src.match(/^data:video\/([^;]+)(?:;[^;]*)*;base64,(.+)$/);
        if (match) {
          blocks.push({ type: "video_url", video_url: { url: src } });
        }
        return;
      }
      if (mediaPositions.has(el)) {
        flushText();
        const media = mediaPositions.get(el)!;
        if (media.type === "image") {
          blocks.push({ type: "image_url", image_url: { url: (media.data as PendingImage).dataUrl } });
        } else if (media.type === "video") {
          blocks.push({ type: "video_url", video_url: { url: (media.data as PendingVideo).dataUrl } });
        }
        return;
      }
      for (const child of Array.from(el.childNodes)) {
        if (child.nodeType === Node.ELEMENT_NODE && (child as HTMLElement).tagName === "BR") {
          currentText += "\n";
        } else {
          walk(child);
        }
      }
      if (el.tagName === "DIV") {
        currentText += "\n";
      }
    }
  };

  for (const child of Array.from(el.childNodes)) {
    walk(child);
  }
  flushText();
  return blocks;
}
