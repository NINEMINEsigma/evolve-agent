import { useEffect, useRef, useState } from "react";
import { TIMING } from "../../constants/timing";
import { fetchActivityOverview } from "./api";
import { subscribeActivityEvents } from "../../services/activityEventBus";
import type {
  ActivityConnectionState,
  ActivityEvent,
  ActivityObservedCounts,
  ActivityOverview,
  ActivityStreamItem,
} from "./types";

const UI_EVENT_LIMIT = 120;

function emptyCounts(): ActivityObservedCounts {
  return { events: 0, messages: 0, responses: 0, tools: 0 };
}

export interface ActivityDashboardState {
  events: ActivityEvent[];
  counts: ActivityObservedCounts;
  gapCount: number;
  connectionState: ActivityConnectionState;
  overview: ActivityOverview | null;
  overviewLoading: boolean;
  overviewError: string | null;
}

export function useActivityDashboard(active: boolean): ActivityDashboardState {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [counts, setCounts] = useState<ActivityObservedCounts>(emptyCounts);
  const [gapCount, setGapCount] = useState(0);
  const [connectionState, setConnectionState] = useState<ActivityConnectionState>("idle");
  const [overview, setOverview] = useState<ActivityOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    generation.current += 1;
    const currentGeneration = generation.current;
    if (!active) {
      setEvents([]);
      setCounts(emptyCounts());
      setGapCount(0);
      setConnectionState("idle");
      setOverview(null);
      setOverviewLoading(false);
      setOverviewError(null);
      return undefined;
    }

    let disposed = false;
    let timer: number | null = null;
    let controller: AbortController | null = null;
    let inFlight = false;

    const refreshOverview = async () => {
      if (disposed || inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      controller = new AbortController();
      setOverviewLoading(true);
      try {
        const next = await fetchActivityOverview(controller.signal);
        if (!disposed && generation.current === currentGeneration) {
          setOverview(next);
          setOverviewError(null);
        }
      } catch (error) {
        if (!disposed && generation.current === currentGeneration && !controller.signal.aborted) {
          setOverviewError(error instanceof Error ? error.message : "活动概览读取失败");
        }
      } finally {
        inFlight = false;
        controller = null;
        if (!disposed) setOverviewLoading(false);
      }
    };

    const startPolling = () => {
      if (timer !== null) window.clearInterval(timer);
      if (document.visibilityState !== "visible") return;
      void refreshOverview();
      timer = window.setInterval(() => void refreshOverview(), TIMING.ACTIVITY_OVERVIEW_POLL_INTERVAL);
    };

    const onEvent = (item: ActivityStreamItem) => {
      if (disposed || generation.current !== currentGeneration) return;
      if ("type" in item) {
        setGapCount((value) => value + item.dropped);
        return;
      }
      setEvents((previous) => [...previous, item].slice(-UI_EVENT_LIMIT));
      setCounts((previous) => ({
        events: previous.events + 1,
        messages: previous.messages + (item.kind === "message_received" ? 1 : 0),
        responses: previous.responses + (item.kind === "agent_response" ? 1 : 0),
        tools: previous.tools + (item.kind === "tool_call" ? 1 : 0),
      }));
    };

    const unsubscribe = subscribeActivityEvents(onEvent, setConnectionState);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") startPolling();
      else {
        if (timer !== null) window.clearInterval(timer);
        timer = null;
        controller?.abort();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    startPolling();

    return () => {
      disposed = true;
      if (timer !== null) window.clearInterval(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
      unsubscribe();
    };
  }, [active]);

  return {
    events,
    counts,
    gapCount,
    connectionState,
    overview,
    overviewLoading,
    overviewError,
  };
}
