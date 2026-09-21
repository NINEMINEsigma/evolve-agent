import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithTimeout, RequestTimeoutError } from "./fetchWithTimeout";

describe("fetchWithTimeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("returns a successful response before the deadline", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("ok"))));
    const response = await fetchWithTimeout("/ok", {}, { timeoutMs: 15000, phase: "test" });
    expect(await response.text()).toBe("ok");
  });

  it("throws RequestTimeoutError when the internal deadline aborts fetch", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })
    )));
    const pending = fetchWithTimeout("/slow", {}, { timeoutMs: 15000, phase: "history_page" });
    await vi.advanceTimersByTimeAsync(15000);
    await expect(pending).rejects.toBeInstanceOf(RequestTimeoutError);
  });

  it("keeps external cancellation as AbortError", async () => {
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })
    )));
    const controller = new AbortController();
    const pending = fetchWithTimeout(
      "/cancelled",
      { signal: controller.signal },
      { timeoutMs: 15000, phase: "history_skeleton" },
    );
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
