import type {
  CharacterAvatarsResponseDto, CharacterProfilesResponseDto, LlmProfile,
} from "@origin/types";
import type { ActivityEvent, ActivityOverview } from "@origin/features/activity/types";
import { PREVIEW } from "../constants";
import content from "../content/zh-CN.json";
import type { PreviewCatalog } from "../types";

function createProfile(name: string, model: string): LlmProfile {
  return {
    name, llm_client_name: "OpenAI", base_url: "https://preview.invalid/v1",
    model, api_key: "", temperature: 0.7, max_output_tokens: 16384,
    reasoning_effort: "high", max_context_tokens: 128000,
    vision_image_profile: null, audio_profile: null, vision_video_profile: null,
    soul_file: "ws:SOUL.md",
  };
}

export function createCatalog(): PreviewCatalog {
  const main = createProfile(PREVIEW.defaultProfile, "demo-reasoning");
  const review = createProfile("Evolve · Review", "demo-review");
  const vision = createProfile("Evolve · Vision", "demo-vision");
  main.vision_image_profile = vision.name;
  review.temperature = 0.3;
  review.max_output_tokens = 8192;
  vision.reasoning_effort = "medium";
  return {
    profiles: [main, review, vision],
    spaces: [
      {
        name: "references", path: "D:/Preview/References",
        description: content.catalog.referenceSpace, is_readonly: true, available: true,
      },
      {
        name: "deliverables", path: "D:/Preview/Deliverables",
        description: content.catalog.deliverableSpace, is_readonly: false, available: true,
      },
    ],
  };
}

export function createCharacterProfiles(): CharacterProfilesResponseDto {
  return {
    characters: [
      {
        name: "Research", character_type: "task",
        directory_path: "ws:characters/task/Research", profile_path: "ws:characters/task/Research/profile.md",
        system_prompt: content.characters.researchPrompt,
        system_prompt_paths: ["ws:characters/task/Research/profile.md"],
        system_prompts: [content.characters.researchPrompt],
        description: content.characters.researchDescription,
        llm_profile_name: "Evolve · Review", profile_available: true, error: null,
      },
      {
        name: "Design", character_type: "task",
        directory_path: "ws:characters/task/Design", profile_path: "ws:characters/task/Design/profile.md",
        system_prompt: content.characters.designPrompt,
        system_prompt_paths: ["ws:characters/task/Design/profile.md"],
        system_prompts: [content.characters.designPrompt],
        description: content.characters.designDescription,
        llm_profile_name: PREVIEW.defaultProfile, profile_available: true, error: null,
      },
      {
        name: "Editor", character_type: "roleplay",
        directory_path: "ws:characters/roleplay/Editor", profile_path: "ws:characters/roleplay/Editor/profile.md",
        system_prompt: content.characters.editorPrompt,
        system_prompt_paths: ["ws:characters/roleplay/Editor/profile.md"],
        system_prompts: [content.characters.editorPrompt],
        description: content.characters.editorDescription,
        llm_profile_name: PREVIEW.defaultProfile, profile_available: true, error: null,
      },
    ],
  };
}

export function createCharacterAvatars(): CharacterAvatarsResponseDto {
  return {
    main: { name: "main-agent", avatar_path: "", avatar_url: null, error: null },
    characters: ["Research", "Design", "Editor"].map((name) => ({
      name, avatar_path: "", avatar_url: null, error: null,
    })),
  };
}

export const ACTIVITY_OVERVIEW: ActivityOverview = {
  session_count: 7, active_loop_count: 2, tool_count: 42, toolset_count: 9,
};

export function createActivityEvents(): ActivityEvent[] {
  const events: ActivityEvent[] = [];
  function append(event: Omit<ActivityEvent, "sequence" | "timestamp">): void {
    const sequence = events.length + 1;
    events.push({
      ...event, sequence,
      timestamp: new Date(PREVIEW.epochMs - 24000 + sequence * 650).toISOString(),
    });
  }

  // 四轮完整活动：两次工具、一处工具、两轮纯文本，总计固定 24 条事件。
  const rounds = [
    { sessionId: PREVIEW.mainSession, character: "main-agent", tools: ["Read", "Write"] },
    { sessionId: PREVIEW.multiSession, character: "Research", tools: ["Read"] },
    { sessionId: PREVIEW.multiSession, character: "Design", tools: [] },
    { sessionId: PREVIEW.mainSession, character: "main-agent", tools: [] },
  ];
  rounds.forEach((round, roundIndex) => {
    const base = {
      session_id: round.sessionId, activity_id: `preview-activity-${roundIndex + 1}`,
      input_sequences: [roundIndex + 1], stream_id: null,
      tool_call_id: null, character_name: round.character, tool_name: null,
      duration_ms: null,
    };
    append({ ...base, kind: "message_received", phase: "observed", status: "observed", character_name: "end-user" });
    for (let turn = 0; turn <= round.tools.length; turn++) {
      const streamId = `${base.activity_id}-stream-${turn}`;
      append({ ...base, kind: "agent_response", phase: "started", status: "active", stream_id: streamId });
      append({
        ...base, kind: "agent_response", phase: "completed", status: "succeeded",
        stream_id: streamId, duration_ms: 420,
      });
      const toolName = round.tools[turn];
      if (toolName === undefined) continue;
      const toolCallId = `${base.activity_id}-tool-${turn}`;
      append({
        ...base, kind: "tool_call", phase: "started", status: "active",
        stream_id: streamId, tool_call_id: toolCallId, tool_name: toolName,
      });
      append({
        ...base, kind: "tool_call", phase: "completed", status: "succeeded",
        stream_id: streamId, tool_call_id: toolCallId, tool_name: toolName, duration_ms: 184,
      });
    }
  });
  return events;
}
