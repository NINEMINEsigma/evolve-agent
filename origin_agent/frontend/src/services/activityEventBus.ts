import type { ActivityConnectionState, ActivityStreamItem } from "../features/activity/types";
import { decodeActivityStreamItem } from "../features/activity/api";

type ActivityListener = (item: ActivityStreamItem) => void;
type StatusListener = (state: ActivityConnectionState) => void;

interface Subscriber {
  onEvent: ActivityListener;
  onStatus: StatusListener;
}

const subscribers = new Set<Subscriber>();
let source: EventSource | null = null;
let sourceGeneration = 0;
let state: ActivityConnectionState = "idle";

function notifyStatus(next: ActivityConnectionState): void {
  state = next;
  for (const subscriber of Array.from(subscribers)) {
    subscriber.onStatus(next);
  }
}

function isCurrent(localSource: EventSource, generation: number): boolean {
  return source === localSource && sourceGeneration === generation;
}

function handlePayload(
  localSource: EventSource,
  generation: number,
  raw: MessageEvent<string>,
): void {
  if (!isCurrent(localSource, generation)) return;
  try {
    const item = decodeActivityStreamItem(JSON.parse(raw.data) as unknown);
    if (item === null) {
      notifyStatus("degraded");
      return;
    }
    for (const subscriber of Array.from(subscribers)) subscriber.onEvent(item);
  } catch (error) {
    console.error("Activity event decode failed", error);
    notifyStatus("degraded");
  }
}

function startSource(): void {
  if (source !== null || subscribers.size === 0) return;
  const generation = ++sourceGeneration;
  const localSource = new EventSource("/api/activity/events");
  source = localSource;
  notifyStatus("connecting");

  localSource.onopen = () => {
    if (isCurrent(localSource, generation)) notifyStatus("live");
  };
  localSource.onerror = () => {
    if (isCurrent(localSource, generation)) notifyStatus("degraded");
  };
  localSource.addEventListener("activity", (event) => {
    handlePayload(localSource, generation, event as MessageEvent<string>);
  });
  localSource.addEventListener("activity_gap", (event) => {
    handlePayload(localSource, generation, event as MessageEvent<string>);
  });
}

function stopSource(): void {
  const localSource = source;
  source = null;
  sourceGeneration += 1;
  if (localSource !== null) localSource.close();
  if (subscribers.size === 0) notifyStatus("idle");
}

export function subscribeActivityEvents(
  onEvent: ActivityListener,
  onStatus: StatusListener,
): () => void {
  const subscriber: Subscriber = { onEvent, onStatus };
  subscribers.add(subscriber);
  onStatus(state);
  startSource();

  let subscribed = true;
  return () => {
    if (!subscribed) return;
    subscribed = false;
    subscribers.delete(subscriber);
    if (subscribers.size === 0) stopSource();
  };
}
