import { useSessionVisualResource } from "./useSessionVisualResource";
import type { SessionVisualResourceState } from "../types/sessionVisual";

export type StageStatus = SessionVisualResourceState["status"];

export interface SessionStageState {
  status: StageStatus;
  reloadKey: number;
  stageUrl: string | null;
  error: string | null;
}

/** 舞台 Hook 只消费服务端最终入口；重定向配置不在浏览器解析。 */
export function useSessionStage(sessionId: string | undefined, paused: boolean = false): SessionStageState {
  const resource = useSessionVisualResource(sessionId, "stage", paused);
  return {
    status: resource.status,
    error: resource.error,
    reloadKey: resource.reloadKey,
    stageUrl: resource.finalUrl,
  };
}
