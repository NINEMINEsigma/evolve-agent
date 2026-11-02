import { useEffect, useState } from "react";
import { CHAT_STYLE } from "../constants/chatStyle";
import { useSessionVisualResource } from "./useSessionVisualResource";
import { scopeSessionChatCss } from "../utils/chatStyleProcessing";
import type { SessionVisualUpdateStatus } from "../types/sessionVisual";
import messages from "../constants/sessionVisualMessages.json";

export type ChatStyleStatus = "idle" | "missing" | "ready" | "error";
export interface SessionChatStyleState {
  status: ChatStyleStatus;
  cssText: string | null;
  error: string | null;
  entryError: string | null;
  updateStatus: SessionVisualUpdateStatus;
  updateError: string | null;
  reloadKey: number;
}

interface CssSnapshot {
  scope: string;
  cssText: string | null;
  error: string | null;
}

export function useSessionChatStyle(sessionId: string | undefined, paused: boolean): SessionChatStyleState {
  const resource = useSessionVisualResource(sessionId, "chat_style", paused);
  const canLoad = !paused && resource.status === "ready" && resource.finalUrl !== null;
  const url = resource.finalUrl;
  const scope = JSON.stringify([sessionId, paused, canLoad, url]);
  const [loaded, setLoaded] = useState<CssSnapshot>({ scope, cssText: null, error: null });

  // Probe errors are deliberately not dependencies: only an actual reload may replace CSS.
  useEffect(() => {
    if (!canLoad || !url) {
      setLoaded({ scope, cssText: null, error: null });
      return;
    }
    let active = true;
    const controller = new AbortController();
    setLoaded((previous) => ({
      scope, cssText: previous.scope === scope ? previous.cssText : null, error: null,
    }));
    const load = async () => {
      try {
        const response = await fetch(url, { cache: "no-store", signal: controller.signal });
        if (!active) return;
        if (!response.ok) throw new Error(`CSS request failed (HTTP ${response.status})`);
        const raw = await response.text();
        if (!active) return;
        if (raw.length > CHAT_STYLE.MAX_BYTES) throw new Error(`CSS exceeds ${CHAT_STYLE.MAX_BYTES} size limit`);
        const result = await scopeSessionChatCss(raw, response.url);
        if (!active) return;
        if (!result.ok) throw new Error(result.error);
        setLoaded({ scope, cssText: result.css, error: null });
      } catch (error) {
        if (!active) return;
        setLoaded({
          scope, cssText: null,
          error: `${messages.styleLoadError}: ${error instanceof Error ? error.message : messages.probeError}`,
        });
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [scope, canLoad, url, resource.reloadKey]);

  const css = loaded.scope === scope && canLoad ? loaded : null;
  const error = resource.status === "error" ? resource.error : css?.error ?? null;
  return {
    status: paused ? "idle" : resource.status === "ready" && css?.error ? "error" : resource.status,
    cssText: css?.cssText ?? null,
    error,
    entryError: resource.error,
    updateStatus: resource.updateStatus,
    updateError: resource.updateError,
    reloadKey: resource.reloadKey,
  };
}
