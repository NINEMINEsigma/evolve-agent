import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLlmProfiles } from "./useLlmProfiles";

const profile = {
  name: "meta",
  llm_client_name: "openai_client",
  base_url: "https://example.invalid/v1",
  model: "model",
  api_key: "secret",
  temperature: 0.2,
  max_output_tokens: 512,
  reasoning_effort: "",
  max_context_tokens: 4096,
  vision_image_profile: null,
  audio_profile: null,
  vision_video_profile: null,
  soul_file: "SOUL.md",
};

function jsonResponse(data: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 409, json: async () => data } as Response;
}

describe("useLlmProfiles metadata role", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/llm/clients") return jsonResponse({ clients: ["openai_client"] });
      if (url === "/api/llm/profiles") return jsonResponse({ profiles: [profile] });
      if (url === "/api/approval/profile") return jsonResponse({ profile_name: null, model: null, available: false });
      if (url === "/api/metadata/profile" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({ state: { profile_name: body.profile_name, model: body.profile_name ? "model" : null, available: Boolean(body.profile_name) } });
      }
      if (url === "/api/metadata/profile") return jsonResponse({ profile_name: "meta", model: "model", available: true });
      throw new Error(`unexpected fetch ${url}`);
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("loads, clears and receives the authoritative metadata Profile state", async () => {
    const { result } = renderHook(() => useLlmProfiles());
    await waitFor(() => expect(result.current.metadataProfileName).toBe("meta"));
    expect(result.current.metadataProfile?.name).toBe("meta");

    await act(async () => {
      await result.current.setMetadataProfile(null);
    });
    expect(result.current.metadataProfileName).toBeNull();

    act(() => {
      result.current.handleMetadataProfileChanged({
        metadata_profile_name: "meta",
        metadata_profile_model: "model",
        metadata_profile_available: true,
      });
    });
    expect(result.current.metadataProfileState).toEqual({
      profile_name: "meta",
      model: "model",
      available: true,
    });
  });
});
