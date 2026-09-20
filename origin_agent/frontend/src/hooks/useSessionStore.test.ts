import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSessionStore } from "./useSessionStore";

function jsonResponse(data: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 502, json: async () => data } as Response;
}

describe("useSessionStore metadata operation feedback", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows an error and clears the independent summary busy state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("regenerate-summary")) return jsonResponse({ detail: "元数据模型不可用" }, false);
      return jsonResponse({ sessions: [] });
    }));
    const { result } = renderHook(() => useSessionStore());

    await act(async () => {
      await result.current.regenerateSummary("s1");
    });

    expect(result.current.generatingSummarySessions.has("s1")).toBe(false);
    expect(result.current.generatingTitleSessions.has("s1")).toBe(false);
    expect(result.current.operationNotice).toEqual({ kind: "error", message: "元数据模型不可用" });
  });

  it("archives successfully and exposes metadata warnings", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/terminate")) {
        return jsonResponse({ terminated: true, metadata_warnings: ["摘要生成失败"] });
      }
      return jsonResponse({ sessions: [] });
    }));
    const { result } = renderHook(() => useSessionStore());

    await act(async () => {
      await result.current.terminateSession("s1");
    });

    expect(result.current.operationNotice?.kind).toBe("warning");
    expect(result.current.operationNotice?.message).toContain("摘要生成失败");
  });

  it("keeps the current selection when merge fallback summary fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ merged: false, error: "父会话摘要失败" })));
    const { result } = renderHook(() => useSessionStore());
    act(() => {
      result.current.setSessions([{
        id: "archived",
        status: "archived",
        created_at: 1,
        title: "",
        parents: [],
        parent: null,
        continuation: null,
        pinned: false,
        last_activity_at: 1,
        tags: [],
        loop_type: "parent",
      }]);
    });

    let newSession: string | undefined;
    await act(async () => {
      newSession = await result.current.mergeSessions(["archived"]);
    });

    expect(newSession).toBeUndefined();
    await waitFor(() => expect(result.current.operationNotice?.message).toBe("父会话摘要失败"));
  });
});
