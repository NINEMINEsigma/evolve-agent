import type { LlmProfile } from "../types";

export type LlmDrawerTab = "profiles" | "references";
export type LlmProfileDraft = Omit<LlmProfile, "temperature" | "max_output_tokens" | "max_context_tokens"> & {
  temperature: string;
  max_output_tokens: string;
  max_context_tokens: string;
};
export interface LlmProfileDraftValidation {
  profile: LlmProfile | null;
  errors: Partial<Record<keyof LlmProfile, string>>;
}
export interface LlmClientGroup {
  client: string;
  baseUrls: { baseUrl: string; profiles: LlmProfile[] }[];
}
export interface LlmEditorState {
  kind: "view" | "edit" | "create";
  selectedName: string;
  originalName: string | null;
  baseline: LlmProfile | null;
  draft: LlmProfileDraft | null;
  busy: boolean;
  error: string | null;
  externalConflict: boolean;
  saveOutcome: "idle" | "saving" | "uncertain";
}
