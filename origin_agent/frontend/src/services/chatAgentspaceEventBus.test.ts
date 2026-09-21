import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentspaceEvent } from "../types";
import {
  publishChatAgentspaceEvent,
  resetChatAgentspaceEventBusForTest,
  subscribeChatAgentspaceEvents,
} from "./chatAgentspaceEventBus";

const event: AgentspaceEvent = {
  sequence: 1,
  kind: "modified",
  source: "watcher",
  path: "sessions/s/stage/index.html",
  new_path: null,
  is_directory: false,
  locks: null,
  timestamp: "2026-09-21T00:00:00Z",
  operation_id: null,
  version: "v1",
  message: null,
};

describe("chatAgentspaceEventBus", () => {
  afterEach(() => {
    resetChatAgentspaceEventBusForTest();
    vi.restoreAllMocks();
  });

  it("fans out events and removes only the unsubscribed listener", () => {
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribeFirst = subscribeChatAgentspaceEvents(first);
    subscribeChatAgentspaceEvents(second);

    publishChatAgentspaceEvent(event);
    unsubscribeFirst();
    unsubscribeFirst();
    publishChatAgentspaceEvent(event);

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);
  });

  it("isolates a failing listener", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const healthy = vi.fn();
    subscribeChatAgentspaceEvents(() => { throw new Error("failed"); });
    subscribeChatAgentspaceEvents(healthy);

    publishChatAgentspaceEvent(event);

    expect(healthy).toHaveBeenCalledOnce();
    expect(console.error).toHaveBeenCalledOnce();
  });
});
