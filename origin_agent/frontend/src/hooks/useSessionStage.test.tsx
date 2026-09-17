import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentspaceEvent } from "../types";
import { useSessionStage } from "./useSessionStage";

const eventBridge = vi.hoisted(() => ({
  handler: null as ((event: AgentspaceEvent) => void) | null,
}));

vi.mock("../services/agentspaceApi", () => ({
  connectAgentspaceEvents: vi.fn((handler: (event: AgentspaceEvent) => void) => {
    eventBridge.handler = handler;
    return () => { eventBridge.handler = null; };
  }),
}));

function stageEvent(
  kind: AgentspaceEvent["kind"],
  path: string | null,
  version: string | null = null,
): AgentspaceEvent {
  return {
    sequence: 1,
    kind,
    source: "watcher",
    path,
    new_path: null,
    is_directory: false,
    locks: null,
    timestamp: new Date().toISOString(),
    operation_id: null,
    version,
    message: null,
  };
}

describe("useSessionStage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    eventBridge.handler = null;
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("", { status: 200 }))));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("treats index.html as the only iframe reload commit marker", async () => {
    const { result } = renderHook(() => useSessionStage("session-a", false));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.status).toBe("ready");
    expect(result.current.reloadKey).toBe(0);

    act(() => {
      eventBridge.handler?.(stageEvent(
        "modified", "sessions/session-a/stage/assets/model.json", "asset-v2",
      ));
      vi.advanceTimersByTime(1500);
    });
    expect(result.current.reloadKey).toBe(0);

    act(() => {
      eventBridge.handler?.(stageEvent(
        "modified", "sessions/session-a/stage/index.html", "index-v2",
      ));
      vi.advanceTimersByTime(1500);
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.reloadKey).toBe(1);

    act(() => {
      eventBridge.handler?.(stageEvent(
        "modified", "sessions/session-a/stage/index.html", "index-v2",
      ));
      vi.advanceTimersByTime(1500);
    });
    expect(result.current.reloadKey).toBe(1);
  });

  it("does not reset a ready stage on SSE resync or transient probe failure", async () => {
    const fetchMock = vi.mocked(fetch);
    const { result } = renderHook(() => useSessionStage("session-a", false));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.status).toBe("ready");
    const url = result.current.stageUrl;

    fetchMock.mockRejectedValueOnce(new Error("temporary network failure"));
    act(() => {
      eventBridge.handler?.(stageEvent("resync", null));
    });
    await act(async () => { await Promise.resolve(); });

    expect(result.current.status).toBe("ready");
    expect(result.current.stageUrl).toBe(url);
    expect(result.current.reloadKey).toBe(0);
  });
});
