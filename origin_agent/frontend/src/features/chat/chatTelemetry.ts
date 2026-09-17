import {
  CHAT_TELEMETRY_MAX_EVENTS,
  CHAT_TELEMETRY_SAMPLE_INTERVAL_MS,
} from "../../constants/telemetry";
import type { ChatTelemetryEvent, ChatTelemetryReport } from "./types";

const ALLOWED_KEYS = new Set<keyof ChatTelemetryEvent>([
  "time",
  "kind",
  "durationMs",
  "count",
  "charCount",
  "startIndex",
  "endIndex",
  "followMode",
  "status",
  "domCount",
  "iframeCount",
]);

type TelemetryListener = () => void;

export class ChatTelemetryController {
  private enabled = false;
  private events: ChatTelemetryEvent[] = [];
  private observers: PerformanceObserver[] = [];
  private sampleTimer: number | null = null;
  private startedAt: string | null = null;
  private stoppedAt: string | null = null;
  private longTaskCount = 0;
  private listeners = new Set<TelemetryListener>();

  subscribe(listener: TelemetryListener): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  snapshot(): { enabled: boolean; eventCount: number; longTaskCount: number; startedAt: string | null } {
    return {
      enabled: this.enabled,
      eventCount: this.events.length,
      longTaskCount: this.longTaskCount,
      startedAt: this.startedAt,
    };
  }

  start(): void {
    if (this.enabled) return;
    this.enabled = true;
    this.startedAt = new Date().toISOString();
    this.stoppedAt = null;
    this.installObserver("longtask", "long_task");
    this.installObserver("event", "event_timing");
    this.sampleTimer = window.setInterval(() => {
      this.record({
        time: Date.now(),
        kind: "dom_sample",
        domCount: document.querySelectorAll(".chat-area *").length,
        iframeCount: document.querySelectorAll(".chat-area iframe").length,
      });
    }, CHAT_TELEMETRY_SAMPLE_INTERVAL_MS);
    this.notify();
  }

  stop(): void {
    if (!this.enabled) return;
    this.enabled = false;
    this.stoppedAt = new Date().toISOString();
    for (const observer of this.observers) observer.disconnect();
    this.observers = [];
    if (this.sampleTimer !== null) {
      clearInterval(this.sampleTimer);
      this.sampleTimer = null;
    }
    this.notify();
  }

  clear(): void {
    this.events = [];
    this.longTaskCount = 0;
    this.startedAt = this.enabled ? new Date().toISOString() : null;
    this.stoppedAt = null;
    this.notify();
  }

  record(event: ChatTelemetryEvent): void {
    if (!this.enabled) return;
    const sanitized: Partial<ChatTelemetryEvent> = {};
    for (const [key, value] of Object.entries(event)) {
      if (ALLOWED_KEYS.has(key as keyof ChatTelemetryEvent)) {
        (sanitized as Record<string, unknown>)[key] = value;
      }
    }
    if (typeof sanitized.time !== "number" || typeof sanitized.kind !== "string") return;
    this.events.push(sanitized as ChatTelemetryEvent);
    if (sanitized.kind === "long_task") this.longTaskCount += 1;
    if (this.events.length > CHAT_TELEMETRY_MAX_EVENTS) {
      this.events.splice(0, this.events.length - CHAT_TELEMETRY_MAX_EVENTS);
    }
    this.notify();
  }

  exportReport(): void {
    const report: ChatTelemetryReport = {
      version: 1,
      startedAt: this.startedAt,
      stoppedAt: this.stoppedAt,
      userAgent: navigator.userAgent,
      events: [...this.events],
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `evolve-chat-telemetry-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  private installObserver(entryType: string, kind: "long_task" | "event_timing"): void {
    if (typeof PerformanceObserver === "undefined") return;
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          this.record({
            time: Date.now(),
            kind,
            durationMs: entry.duration,
          });
        }
      });
      observer.observe({ type: entryType, buffered: true });
      this.observers.push(observer);
    } catch {
      // 当前浏览器不支持相应 PerformanceEntry 类型时降级为无该指标。
    }
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

export const chatTelemetry = new ChatTelemetryController();
