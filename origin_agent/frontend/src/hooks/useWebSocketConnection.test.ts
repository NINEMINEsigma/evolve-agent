import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WS_CLOSE_SESSION_DELETED } from "../constants/ws";
import { TIMING } from "../constants/timing";
import { useWebSocketConnection } from "./useWebSocketConnection";

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  send = vi.fn();

  constructor(url: string | URL) {
    this.url = String(url);
    MockWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  emitClose(code: number): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code }));
  }

  close(code = 1000): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code }));
  }
}

function statusResponse(exists: boolean, occupied = false): Response {
  return new Response(JSON.stringify({ exists, occupied }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useWebSocketConnection session deletion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("stops reconnecting when an established session closes with the deletion code", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(statusResponse(true))));
    const onSessionDeleted = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onSessionDeleted }));
    await act(async () => { await result.current.connect("session-a"); });
    const socket = MockWebSocket.instances[0];
    act(() => socket.open());
    act(() => socket.emitClose(WS_CLOSE_SESSION_DELETED));
    await act(async () => { vi.advanceTimersByTime(TIMING.WS_MAX_RECONNECT_DELAY); });

    expect(onSessionDeleted).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(result.current.status).toBe("会话已删除");
    unmount();
  });

  it("does not create a socket when the pre-check reports a missing session", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(statusResponse(false))));
    const onSessionDeleted = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onSessionDeleted }));
    await act(async () => { await result.current.connect("session-a"); });

    expect(onSessionDeleted).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(0);
    expect(result.current.status).toBe("会话已删除");
    unmount();
  });

  it("uses the status re-check when a handshake rejection loses the private close code", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(statusResponse(true))
      .mockResolvedValueOnce(statusResponse(false));
    vi.stubGlobal("fetch", fetchMock);
    const onSessionDeleted = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onSessionDeleted }));
    await act(async () => { await result.current.connect("session-a"); });
    act(() => MockWebSocket.instances[0].emitClose(1006));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onSessionDeleted).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("会话已删除");
    unmount();
  });

  it("keeps exponential reconnect behavior for an ordinary established disconnect", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(statusResponse(true))));
    const onClose = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onClose }));
    await act(async () => { await result.current.connect("session-a"); });
    act(() => MockWebSocket.instances[0].open());
    act(() => MockWebSocket.instances[0].emitClose(1006));
    await act(async () => {
      vi.advanceTimersByTime(TIMING.WS_RECONNECT_BASE);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances).toHaveLength(2);
    unmount();
  });
});
