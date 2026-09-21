import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchHistoryPage, fetchHistoryResources, fetchHistorySkeleton } from "./historyApi";

function jsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("historyApi request deadlines", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("passes through skeleton and page responses", async () => {
    const fetchMock = vi.fn((url: string) => Promise.resolve(jsonResponse(
      url.includes("/skeleton")
        ? { session_id: "s", start_index: 0, history_count: 0, row_count: 0, rows: [] }
        : { session_id: "s", start_index: 0, end_index: 0, history_count: 0, rows: [] },
    )));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await fetchHistorySkeleton("s", 0, controller.signal);
    await fetchHistoryPage("s", 0, 80, controller.signal);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps resources on the plain fetch path", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({
      session_id: "s", history_count: 0, images: [], downloads: [],
    })));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await fetchHistoryResources("s", controller.signal);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/s/history/resources",
      { signal: controller.signal },
    );
  });
});
