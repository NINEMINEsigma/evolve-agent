import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentspaceEvent } from "../types";
import { useSessionChatStyle } from "./useSessionChatStyle";

const eventBridge = vi.hoisted(() => ({
  handler: null as ((event: AgentspaceEvent) => void) | null,
}));

vi.mock("../services/chatAgentspaceEventBus", () => ({
  subscribeChatAgentspaceEvents: vi.fn((handler: (event: AgentspaceEvent) => void) => {
    eventBridge.handler = handler;
    return () => { eventBridge.handler = null; };
  }),
}));

function styleEvent(kind: AgentspaceEvent["kind"], path: string | null): AgentspaceEvent {
  return {
    sequence: 1,
    kind,
    source: "watcher",
    path,
    new_path: null,
    is_directory: false,
    locks: null,
    timestamp: "2026-09-21T00:00:00Z",
    operation_id: null,
    version: "v1",
    message: null,
  };
}

describe("useSessionChatStyle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    eventBridge.handler = null;
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(".message { color: red; }", { status: 200 }))));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("ignores other session paths and reloads the current style", async () => {
    const { result } = renderHook(() => useSessionChatStyle("session-a", false));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => {
      eventBridge.handler?.(styleEvent("modified", "sessions/session-b/chat-style/index.css"));
      vi.advanceTimersByTime(500);
    });
    expect(result.current.reloadKey).toBe(0);

    act(() => {
      eventBridge.handler?.(styleEvent("modified", "sessions/session-a/chat-style/index.css"));
      vi.advanceTimersByTime(500);
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.reloadKey).toBe(1);
  });

  it("restores the default style when the entry is deleted", async () => {
    const { result } = renderHook(() => useSessionChatStyle("session-a", false));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    act(() => {
      eventBridge.handler?.(styleEvent("deleted", "sessions/session-a/chat-style/index.css"));
    });
    expect(result.current.status).toBe("missing");
    expect(result.current.cssText).toBeNull();
  });
});
