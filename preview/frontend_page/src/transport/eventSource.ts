import type { PreviewRuntime } from "../types";
import { createActivityEvents } from "../data/catalog";
import { PREVIEW } from "../constants";
import { reportPreviewFault } from "../runtime/faults";

export class PreviewEventSource extends EventTarget {
  static readonly CONNECTING = 0; static readonly OPEN = 1; static readonly CLOSED = 2;
  readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSED = 2;
  readyState: number = PreviewEventSource.CONNECTING;
  readonly url: string;
  readonly withCredentials = false;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private cleanups: Array<() => void> = [];
  constructor(input: string | URL, private readonly runtime: PreviewRuntime) {
    super();
    const url = new URL(input, location.href); this.url = url.href;
    const channel = url.pathname === "/api/activity/events" ? "activity" : url.pathname === "/api/agentspace/events" ? "agentspace" : null;
    if (!channel || url.origin !== location.origin) {
      reportPreviewFault({ code: "eventsource_url", path: url.pathname, message: "Unregistered preview event stream" });
      throw new DOMException("Preview blocks this event stream", "SecurityError");
    }
    this.cleanups.push(runtime.events.schedule(() => {
      if (this.readyState === PreviewEventSource.CLOSED) return;
      this.readyState = PreviewEventSource.OPEN;
      const opened = new Event("open"); this.dispatchEvent(opened); this.onopen?.(opened);
      this.cleanups.push(runtime.events.subscribe(channel, (name, value) => this.emit(name, value)));
      if (channel === "agentspace") this.emit("agentspace", { sequence: 0, kind: "resync", source: "system", path: null,
        new_path: null, is_directory: null, locks: null, timestamp: PREVIEW.timestamp, operation_id: null, version: null, message: null });
      else {
        const events = createActivityEvents();
        let index = 0;
        const tick = () => {
          if (this.readyState !== PreviewEventSource.OPEN) return;
          if (!runtime.paused && index < events.length) this.emit("activity", events[index++]);
          if (index < events.length) this.cleanups.push(runtime.events.schedule(tick, 120));
        };
        tick();
      }
    }, 0));
  }
  private emit(name: string, value: unknown): void {
    if (this.readyState !== PreviewEventSource.OPEN) return;
    const event = new MessageEvent<string>(name, { data: JSON.stringify(value), origin: location.origin });
    this.dispatchEvent(event);
    if (name === "message") this.onmessage?.(event);
  }
  close(): void {
    this.readyState = PreviewEventSource.CLOSED;
    for (const cleanup of this.cleanups.splice(0)) cleanup();
  }
}
