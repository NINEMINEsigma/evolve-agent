import type { MessageContent } from "@origin/types";
import type { PreviewRuntime, PreviewSocketSink } from "../types";
import { syncHistory, enqueueReply } from "../runtime/conversation";
import { objectBody, strings, text } from "./contracts";
import { reportPreviewFault } from "../runtime/faults";
import labels from "../content/zh-CN.json";

export class PreviewWebSocket extends EventTarget implements PreviewSocketSink {
  static readonly CONNECTING = 0; static readonly OPEN = 1; static readonly CLOSING = 2; static readonly CLOSED = 3;
  readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSING = 2; readonly CLOSED = 3;
  readyState: number = PreviewWebSocket.CONNECTING;
  readonly url: string;
  readonly protocol = ""; readonly extensions = ""; readonly bufferedAmount = 0;
  binaryType: BinaryType = "blob";
  sessionId = "";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private removeSocket: (() => void) | null = null;
  private cancelOpen: (() => void) | null = null;
  constructor(input: string | URL, private readonly runtime: PreviewRuntime) {
    super();
    const url = new URL(input, location.href);
    this.url = url.href;
    if (url.host !== location.host || !["ws:", "wss:"].includes(url.protocol) || url.pathname !== "/ws/chat") {
      reportPreviewFault({ code: "websocket_url", path: url.pathname, message: "Only the in-memory chat socket is allowed" });
      throw new DOMException("Preview blocks this socket", "SecurityError");
    }
    const resume = url.searchParams.get("resume");
    this.sessionId = resume || runtime.store.createSession().info.id;
    this.cancelOpen = runtime.events.schedule(() => {
      if (this.readyState !== PreviewWebSocket.CONNECTING) return;
      if (!runtime.store.sessions.has(this.sessionId)) { this.terminate(4004); return; }
      this.readyState = PreviewWebSocket.OPEN;
      this.removeSocket = runtime.events.addSocket(this);
      const opened = new Event("open"); this.dispatchEvent(opened); this.onopen?.(opened);
      const session = runtime.store.session(this.sessionId);
      syncHistory(runtime, this.sessionId);
      this.emit({ type: "handsfree_mode", session_id: this.sessionId, approval_mode: session.approvalMode });
      if (session.confirm) this.emit({ type: "confirm_request", session_id: this.sessionId, ...session.confirm });
      if (session.ask) this.emit({ type: "ask_request", session_id: this.sessionId, ...session.ask });
      for (const subagent of Object.values(session.subagents)) this.emit({ type: "subagent_update", session_id: this.sessionId, result: JSON.stringify({ ...subagent, feedback: [] }) });
    }, 0);
  }
  emit: PreviewSocketSink["emit"] = (message) => {
    if (this.readyState !== PreviewWebSocket.OPEN) return;
    const event = new MessageEvent<string>("message", { data: JSON.stringify(message), origin: location.origin });
    this.dispatchEvent(event); this.onmessage?.(event);
  };
  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (this.readyState !== PreviewWebSocket.OPEN) throw new DOMException("Preview socket is not open", "InvalidStateError");
    try {
      if (typeof data !== "string") throw new Error("Only JSON text frames are supported");
      const body = objectBody(JSON.parse(data));
      const session = this.runtime.store.session(this.sessionId);
      switch (body.type) {
        case "ping": this.emit({ type: "pong" }); return;
        case "handsfree_mode":
          if (body.content !== "manual" && body.content !== "handsfree" && body.content !== "yolo") throw new Error("Invalid approval mode");
          session.approvalMode = body.content;
          this.runtime.events.schedule(() => {
            if (this.readyState === PreviewWebSocket.OPEN) this.emit({ type: "handsfree_mode", session_id: this.sessionId, approval_mode: session.approvalMode });
          }, 0);
          return;
        case "user_message": {
          this.runtime.store.writable(this.sessionId);
          if (typeof body.content !== "string" && !Array.isArray(body.content)) throw new Error("Invalid user content");
          const profileName = text(body.llm_profile_name);
          if (!this.runtime.store.profiles.some((item) => item.name === profileName)) throw new Error("Unknown preview profile");
          enqueueReply(this.runtime, this.sessionId, {
            content: body.content as MessageContent, profileName,
            clientMessageId: body.client_message_id === undefined ? undefined : text(body.client_message_id),
            characterName: body.character_name === undefined ? undefined : text(body.character_name),
            targetSessions: body.target_sessions === undefined ? undefined : strings(body.target_sessions),
            requireToolCall: body.require_tool_call === true,
          }); return;
        }
        case "file_upload": this.emit({ type: "system", session_id: this.sessionId, content: JSON.stringify({ uploaded: true, filename: text(body.filename), path: "ws:uploads/preview" }) }); return;
        case "client_diagnostic": return;
        default: throw new Error("Unregistered outgoing preview frame");
      }
    } catch (error) {
      reportPreviewFault({ code: "websocket_frame", message: error instanceof Error ? error.message : "Invalid socket frame" });
      this.emit({ type: "error", session_id: this.sessionId, content: labels.ui.failed });
    }
  }
  close(code = 1000, reason = ""): void {
    if (this.readyState === PreviewWebSocket.CLOSED) return;
    this.readyState = PreviewWebSocket.CLOSING;
    this.cancelOpen?.(); this.removeSocket?.(); this.cancelOpen = null; this.removeSocket = null;
    this.readyState = PreviewWebSocket.CLOSED;
    const closed = new CloseEvent("close", { code, reason, wasClean: true });
    this.dispatchEvent(closed); this.onclose?.(closed);
  }
  terminate = (code: number): void => { this.close(code); };
}
