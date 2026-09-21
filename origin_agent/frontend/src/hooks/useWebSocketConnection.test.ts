import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WS_CLOSE_SESSION_DELETED } from "../constants/ws";
import { RequestTimeoutError } from "../services/fetchWithTimeout";
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

  it("reports a pre-check timeout and still attempts the WebSocket connection", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(
      new RequestTimeoutError("session_status_precheck", 15000, 15001),
    )));
    const onTransportDiagnostic = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onTransportDiagnostic }));
    await act(async () => { await result.current.connect("session-a"); });
    expect(onTransportDiagnostic).toHaveBeenCalledOnce();
    expect(MockWebSocket.instances).toHaveLength(1);
    unmount();
  });

  it("does not report cancellation after disconnecting an in-flight pre-check", async () => {
    let rejectFetch!: (error: Error) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((_resolve, reject) => {
      rejectFetch = reject;
    })));
    const onTransportDiagnostic = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onTransportDiagnostic }));
    const pending = result.current.connect("session-a");
    act(() => result.current.disconnect());
    rejectFetch(new DOMException("aborted", "AbortError"));
    await act(async () => { await pending; });
    expect(onTransportDiagnostic).not.toHaveBeenCalled();
    expect(MockWebSocket.instances).toHaveLength(0);
    unmount();
  });

  it("reports a status re-check timeout without deleting the session", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(statusResponse(true))
      .mockRejectedValueOnce(new RequestTimeoutError("session_status_recheck", 15000, 15001));
    vi.stubGlobal("fetch", fetchMock);
    const onTransportDiagnostic = vi.fn();
    const onSessionDeleted = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocketConnection());

    act(() => result.current.setHandlers({ onTransportDiagnostic, onSessionDeleted }));
    await act(async () => { await result.current.connect("session-a"); });
    act(() => MockWebSocket.instances[0].emitClose(1006));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(onTransportDiagnostic).toHaveBeenCalledOnce();
    expect(onSessionDeleted).not.toHaveBeenCalled();
    expect(result.current.status).toBe("连接诊断超时");
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
