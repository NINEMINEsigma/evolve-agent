export * from "@preview-original/media-api";
import { createSeedSessions } from "../data/sessions";
import { DEMO_ASSETS, PREVIEW_MEDIA_URLS } from "../constants";
import { createPreviewWavBlob } from "./audioRecorder";
import { reportPreviewFault } from "../runtime/faults";

let audioUrl: string | null = null;
let mediaMap: Map<string, { type: "image" | "audio" | "video"; url: string; available: boolean }> | null = null;

function registeredMedia() {
  if (mediaMap) return mediaMap;
  mediaMap = new Map();
  for (const session of createSeedSessions()) {
    for (const item of session.media) {
      const imageUrl = item.source_path?.endsWith("diagram.svg") || item.media_id.endsWith("-diagram")
        ? DEMO_ASSETS.diagram : DEMO_ASSETS.cover;
      mediaMap.set(`${session.info.id}/${item.media_id}`, {
        type: item.media_type, url: imageUrl, available: item.preview_available,
      });
    }
  }
  return mediaMap;
}

export function mediaContentUrl(sessionId: string, mediaId: string): string {
  const key = `${sessionId}/${mediaId}`;
  if (PREVIEW_MEDIA_URLS.has(key)) return PREVIEW_MEDIA_URLS.get(key)!;
  const media = registeredMedia().get(key);
  if (!media) {
    reportPreviewFault({ code: "media_missing", message: "Media identity is not registered", path: `${sessionId}/${mediaId}` });
    throw new Error("Unknown preview media identity");
  }
  if (media.type === "video") {
    // 正式组件在不可预览状态仍调用此函数；空地址不会挂载 video，保留其原生不可用提示。
    if (media.available) {
      reportPreviewFault({ code: "video_preview", message: "Video seed must declare preview_available=false" });
      throw new Error("Preview video is unavailable; the seed must mark it unavailable");
    }
    return "";
  }
  if (media.type === "audio") {
    if (!audioUrl) audioUrl = URL.createObjectURL(createPreviewWavBlob());
    return audioUrl;
  }
  return media.url;
}

window.addEventListener("pagehide", () => {
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = null;
});
