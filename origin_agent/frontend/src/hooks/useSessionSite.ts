import { useMemo } from "react";
import { useSessionVisualResource } from "./useSessionVisualResource";
import { buildSiteUrls } from "../utils";

export type SiteStatus = "idle" | "missing" | "ready";

export interface SessionSiteState {
  status: SiteStatus;
  reloadKey: number;
  urls: ReturnType<typeof buildSiteUrls>;
  refresh: () => void;
}

export function useSessionSite(sessionId: string | undefined): SessionSiteState {
  const resource = useSessionVisualResource(sessionId, "site");
  const sourceUrls = useMemo(() => buildSiteUrls(sessionId ?? ""), [sessionId]);
  const urls = sourceUrls && resource.finalUrl
    ? { ...sourceUrls, indexUrl: resource.finalUrl }
    : sourceUrls;
  return {
    status: resource.status === "ready" ? "ready" : resource.status === "idle" ? "idle" : "missing",
    reloadKey: resource.reloadKey,
    urls,
    refresh: resource.refresh,
  };
}
