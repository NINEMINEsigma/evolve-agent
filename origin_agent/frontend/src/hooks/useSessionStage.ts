import { useSessionVisualResource } from "./useSessionVisualResource";

export type StageStatus = "idle" | "missing" | "ready";

export interface SessionStageState {
  status: StageStatus;
  reloadKey: number;
  stageUrl: string | null;
}

/** 舞台 Hook 只消费服务端最终入口；重定向配置不在浏览器解析。 */
export function useSessionStage(sessionId: string | undefined, paused: boolean = false): SessionStageState {
  const resource = useSessionVisualResource(sessionId, "stage", paused);
  return {
    status: resource.status === "ready" ? "ready" : resource.status === "idle" ? "idle" : "missing",
    reloadKey: resource.reloadKey,
    stageUrl: resource.finalUrl,
  };
}
