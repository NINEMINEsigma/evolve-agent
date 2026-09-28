import type { LlmProfile } from "../types";

/** 新建 Profile 的默认值；每次编辑必须复制，不修改共享对象。 */
export const EMPTY_LLM_PROFILE: Readonly<LlmProfile> = {
  name: "", llm_client_name: "openai_client", base_url: "", model: "", api_key: "",
  temperature: 0.7, max_output_tokens: 4096, reasoning_effort: "", max_context_tokens: 128000,
  vision_image_profile: null, audio_profile: null, vision_video_profile: null, soul_file: "SOUL.md",
};

/** 数字草稿字段，编辑期间保留原始字符串。 */
export const LLM_NUMERIC_FIELDS = ["temperature", "max_output_tokens", "max_context_tokens"] as const;
/** 完整字段清单，用于无密钥输出的内存比较。 */
export const LLM_PROFILE_FIELDS = Object.keys(EMPTY_LLM_PROFILE) as (keyof LlmProfile)[];
/** 顶部模型菜单尺寸，单位 px。 */
export const MODEL_MENU = { WIDTH: 360, MAX_HEIGHT: 420, VIEWPORT_MARGIN: 8, ANCHOR_GAP: 6, MIN_TARGET: 44 } as const;
