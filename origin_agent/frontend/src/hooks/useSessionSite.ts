import { useMemo } from "react";
import { useSessionVisualResource } from "./useSessionVisualResource";
import { buildSiteUrls } from "../utils";
import type { SessionVisualResourceState, SessionVisualUpdateStatus } from "../types/sessionVisual";

export type SiteStatus = SessionVisualResourceState["status"];

export interface SessionSiteState {
  status: SiteStatus;
  reloadKey: number;
  urls: ReturnType<typeof buildSiteUrls>;
  refresh: () => void;
  error: string | null;
  updateStatus: SessionVisualUpdateStatus;
  updateError: string | null;
}

export function useSessionSite(sessionId: string | undefined): SessionSiteState {
  const resource = useSessionVisualResource(sessionId, "site");
  const sourceUrls = useMemo(() => buildSiteUrls(sessionId ?? ""), [sessionId]);
  const urls = sourceUrls && resource.finalUrl
    ? { ...sourceUrls, indexUrl: resource.finalUrl }
    : sourceUrls;
  return {
    status: resource.status,
    error: resource.error,
    updateStatus: resource.updateStatus,
    updateError: resource.updateError,
    reloadKey: resource.reloadKey,
    urls,
    refresh: resource.refresh,
  };
}
