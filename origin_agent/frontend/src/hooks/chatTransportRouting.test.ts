import { describe, expect, it, vi } from "vitest";
import type { AgentspaceEvent, ClientDiagnostic } from "../types";
import { clientDiagnosticFrame, routeChatTransportMessage } from "./chatTransportRouting";

const event: AgentspaceEvent = {
  sequence: 1,
  kind: "resync",
  source: "system",
  path: null,
  new_path: null,
  is_directory: null,
  locks: null,
  timestamp: "2026-09-21T00:00:00Z",
  operation_id: null,
  version: null,
  message: null,
};

describe("chatTransportRouting", () => {
  it("publishes a current-session Agentspace event and consumes the message", () => {
    const publish = vi.fn();
    const consumed = routeChatTransportMessage({
      type: "agentspace_event",
      session_id: "s",
      agentspace_event: event,
    }, "s", publish);
    expect(consumed).toBe(true);
    expect(publish).toHaveBeenCalledWith(event);
  });

  it("consumes but ignores an event from another session", () => {
    const publish = vi.fn();
    expect(routeChatTransportMessage({
      type: "agentspace_event",
      session_id: "other",
      agentspace_event: event,
    }, "s", publish)).toBe(true);
    expect(publish).not.toHaveBeenCalled();
  });

  it("builds a diagnostic frame without chat content", () => {
    const diagnostic: ClientDiagnostic = {
      kind: "critical_request_timeout",
      phase: "history_page",
      duration_ms: 15000,
      websocket_state: "OPEN",
    };
    const frame = clientDiagnosticFrame("s", diagnostic);
    expect(frame.type).toBe("client_diagnostic");
    expect(frame.client_diagnostic).toBe(diagnostic);
    expect(frame.content).toBeUndefined();
    expect(frame.message).toBeUndefined();
  });
});
