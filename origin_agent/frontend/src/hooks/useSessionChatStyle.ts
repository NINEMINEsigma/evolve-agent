import { useCallback, useEffect, useState } from "react";
import { CHAT_STYLE } from "../constants/chatStyle";
import { useSessionVisualResource } from "./useSessionVisualResource";
import { scopeSessionChatCss } from "../utils/chatStyleProcessing";

export type ChatStyleStatus = "idle" | "missing" | "ready" | "error";
export interface SessionChatStyleState {
  status: ChatStyleStatus;
  cssText: string | null;
  error: string | null;
  reloadKey: number;
}

export function useSessionChatStyle(sessionId: string | undefined, paused: boolean): SessionChatStyleState {
  const resource = useSessionVisualResource(sessionId, "chat_style", paused);
  const [cssText, setCssText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!resource.finalUrl || resource.status !== "ready") {
      setCssText(null);
      setError(resource.error);
      return;
    }
    try {
      const response = await fetch(resource.finalUrl, { cache: "no-store" });
      if (!response.ok) throw new Error("CSS 文件加载失败");
      const raw = await response.text();
      if (raw.length > CHAT_STYLE.MAX_BYTES) throw new Error(`CSS 文件超过 ${CHAT_STYLE.MAX_BYTES} 字节上限`);
      const result = await scopeSessionChatCss(raw, response.url);
      if (!result.ok) throw new Error(result.error);
      setCssText(result.css);
      setError(null);
    } catch (caught) {
      setCssText(null);
      setError(caught instanceof Error ? caught.message : "CSS 文件加载失败");
    }
  }, [resource.finalUrl, resource.status, resource.error]);

  useEffect(() => { void load(); }, [load, resource.reloadKey]);

  return {
    status: resource.status === "error" ? "error" : resource.status,
    cssText,
    error,
    reloadKey: resource.reloadKey,
  };
}
