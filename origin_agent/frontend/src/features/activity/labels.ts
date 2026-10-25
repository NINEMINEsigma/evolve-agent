import data from "./labels.json";
import type { ActivityEventKind, ActivityEventPhase, ActivityEventStatus, ActivityConnectionState } from "./types";

type Labels = {
  title: string;
  connection: Record<ActivityConnectionState, string>;
  kpi: { sessions: string; loops: string; tools: string; toolsets: string; observed: string };
  events: Record<ActivityEventKind | ActivityEventPhase | ActivityEventStatus | "gap", string>;
  empty: string;
  overviewError: string;
  gapDetail: string;
};

export const activityLabels = data as Labels;
