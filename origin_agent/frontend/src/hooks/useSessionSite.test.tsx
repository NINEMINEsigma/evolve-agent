import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentspaceEvent } from "../types";
import { useSessionSite } from "./useSessionSite";

const eventBridge = vi.hoisted(() => ({
  handler: null as ((event: AgentspaceEvent) => void) | null,
  cleanup: vi.fn(),
}));

vi.mock("../services/chatAgentspaceEventBus", () => ({
  subscribeChatAgentspaceEvents: vi.fn((handler: (event: AgentspaceEvent) => void) => {
    eventBridge.handler = handler;
    return eventBridge.cleanup;
  }),
}));

function siteEvent(kind: AgentspaceEvent["kind"], path: string | null): AgentspaceEvent {
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

describe("useSessionSite", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    eventBridge.handler = null;
    eventBridge.cleanup.mockClear();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("", { status: 200 }))));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("ignores other sessions and refreshes the current site after the quiet window", async () => {
    const { result, unmount } = renderHook(() => useSessionSite("session-a"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.status).toBe("ready");

    act(() => {
      eventBridge.handler?.(siteEvent("modified", "sessions/session-b/site/index.html"));
      vi.advanceTimersByTime(1500);
    });
    expect(result.current.reloadKey).toBe(0);

    act(() => {
      eventBridge.handler?.(siteEvent("modified", "sessions/session-a/site/index.html"));
      vi.advanceTimersByTime(1500);
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.reloadKey).toBe(1);

    unmount();
    expect(eventBridge.cleanup).toHaveBeenCalledOnce();
  });

  it("marks the current entry missing when it is deleted", async () => {
    const { result } = renderHook(() => useSessionSite("session-a"));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    act(() => {
      eventBridge.handler?.(siteEvent("deleted", "sessions/session-a/site/index.html"));
    });
    expect(result.current.status).toBe("missing");
  });
});
