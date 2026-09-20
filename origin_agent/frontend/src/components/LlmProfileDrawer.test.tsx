import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LlmProfileDrawer from "./LlmProfileDrawer";

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

describe("LlmProfileDrawer metadata role", () => {
  it("shows an independent metadata role button and clears after confirmation", async () => {
    const setMetadataProfile = vi.fn(async () => ({ profile_name: null, model: null, available: false }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <LlmProfileDrawer
        open
        onClose={() => {}}
        llmProfiles={{
          profiles: [profile],
          activeProfileName: "",
          approvalProfileName: null,
          metadataProfileName: "meta",
          setApprovalProfile: vi.fn(),
          setMetadataProfile,
          createProfile: vi.fn(),
          updateProfile: vi.fn(),
          deleteProfile: vi.fn(),
          availableClients: ["openai_client"],
          setActiveProfile: vi.fn(),
          error: null,
        } as any}
      />,
    );

    const button = await screen.findByRole("button", { name: "◆" });
    expect(button).toHaveAttribute("data-tooltip", "全局元数据 Profile（点击清除）");
    fireEvent.click(button);
    expect(window.confirm).toHaveBeenCalled();
    expect(setMetadataProfile).toHaveBeenCalledWith(null);
  });
});
