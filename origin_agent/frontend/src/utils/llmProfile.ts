import type { LlmProfile } from "../types";
import type { LlmClientGroup, LlmProfileDraft, LlmProfileDraftValidation } from "../types/llmProfileUi";
import { LLM_NUMERIC_FIELDS, LLM_PROFILE_FIELDS } from "../constants/llmProfile";

export function groupLlmProfiles(profiles: LlmProfile[], query: string): LlmClientGroup[] {
  const groups = new Map<string, Map<string, LlmProfile[]>>();
  const needle = query.trim().toLocaleLowerCase();
  for (const profile of profiles) {
    if (needle && ![profile.name, profile.model, profile.llm_client_name, profile.base_url]
      .some((value) => value.toLocaleLowerCase().includes(needle))) continue;
    let urls = groups.get(profile.llm_client_name);
    if (!urls) { urls = new Map(); groups.set(profile.llm_client_name, urls); }
    const entries = urls.get(profile.base_url) ?? [];
    entries.push(profile);
    urls.set(profile.base_url, entries);
  }
  return Array.from(groups, ([client, urls]) => ({
    client,
    baseUrls: Array.from(urls, ([baseUrl, entries]) => ({
      baseUrl, profiles: entries.slice().sort((a, b) => a.name.localeCompare(b.name)),
    })).sort((a, b) => a.baseUrl.localeCompare(b.baseUrl)),
  })).sort((a, b) => a.client.localeCompare(b.client));
}

export function createLlmProfileDraft(profile: LlmProfile): LlmProfileDraft {
  return { ...profile, temperature: String(profile.temperature), max_output_tokens: String(profile.max_output_tokens), max_context_tokens: String(profile.max_context_tokens) };
}

export function validateLlmProfileDraft(
  draft: LlmProfileDraft, profiles: LlmProfile[], originalName: string | null,
): LlmProfileDraftValidation {
  const errors: LlmProfileDraftValidation["errors"] = {};
  const name = draft.name.trim();
  if (!name) errors.name = "请输入配置名称";
  else if (profiles.some((profile) => profile.name === name && profile.name !== originalName)) errors.name = "配置名称已存在";
  const numbers = { temperature: Number(draft.temperature), max_output_tokens: Number(draft.max_output_tokens), max_context_tokens: Number(draft.max_context_tokens) };
  for (const field of LLM_NUMERIC_FIELDS) {
    if (!draft[field].trim() || !Number.isFinite(numbers[field])) errors[field] = "请输入有效数字";
    else if (field !== "temperature" && !Number.isInteger(numbers[field])) errors[field] = "请输入整数";
  }
  return { profile: Object.keys(errors).length ? null : { ...draft, ...numbers, name }, errors };
}

export function generateDuplicateName(sourceName: string, existingNames: string[]): string {
  let index = 1;
  while (existingNames.includes(`${sourceName}${index}`)) index++;
  return `${sourceName}${index}`;
}

export function sameLlmProfile(a: LlmProfile, b: LlmProfile): boolean {
  return LLM_PROFILE_FIELDS.every((field) => a[field] === b[field]);
}
