import type { LlmProfile, ModalityType, DynamicSandboxSpaceWithAvailability } from "@origin/types";
import type { PreviewRuntime } from "../types";
import { createCharacterProfiles, createCharacterAvatars, ACTIVITY_OVERVIEW } from "../data/catalog";
import { PREVIEW } from "../constants";
import { PreviewHttpError, flag, integer, jsonResponse, objectBody, readBody, text } from "./contracts";
import labels from "../content/zh-CN.json";

function profileInput(value: unknown): LlmProfile {
  const body = objectBody(value);
  const nullable = (value: unknown) => value === null ? null : text(value);
  if (typeof body.temperature !== "number" || !Number.isFinite(body.temperature)) throw new PreviewHttpError(422, "Invalid temperature");
  return {
    name: text(body.name), llm_client_name: text(body.llm_client_name), base_url: text(body.base_url),
    model: text(body.model), api_key: text(body.api_key), temperature: body.temperature,
    max_output_tokens: integer(body.max_output_tokens, 1), max_context_tokens: integer(body.max_context_tokens, 1),
    reasoning_effort: text(body.reasoning_effort), soul_file: text(body.soul_file),
    vision_image_profile: nullable(body.vision_image_profile), audio_profile: nullable(body.audio_profile), vision_video_profile: nullable(body.vision_video_profile),
  };
}
function sandboxInput(value: unknown): DynamicSandboxSpaceWithAvailability {
  const body = objectBody(value);
  const name = text(body.name);
  if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(name)) throw new PreviewHttpError(422, "Invalid namespace name");
  return { name, path: text(body.path), description: text(body.description), is_readonly: flag(body.is_readonly), available: true };
}
export async function handleConfigRequest(request: Request, runtime: PreviewRuntime): Promise<Response | null> {
  const url = new URL(request.url), path = url.pathname, method = request.method;
  const store = runtime.store;
  if (path === "/api/llm/profiles") {
    if (method === "GET") return jsonResponse({ profiles: store.profiles });
    const body = await readBody(request);
    if (method === "POST" || method === "PUT") {
      const profile = profileInput(method === "POST" ? body : body.profile);
      const original = method === "PUT" ? text(body.profile_name) : null;
      if (!profile.name.trim()) throw new PreviewHttpError(422, "Profile name cannot be blank");
      if (original && !store.profiles.some((item) => item.name === original)) throw new PreviewHttpError(404, "Profile does not exist");
      if (store.profiles.some((item) => item.name === profile.name && item.name !== original)) throw new PreviewHttpError(409, "Profile name is already used");
      const exists = (name: string | null) => name === null || name === profile.name || store.profiles.some((item) => item.name === name);
      if (![profile.vision_image_profile, profile.audio_profile, profile.vision_video_profile].every(exists)) throw new PreviewHttpError(422, "Unknown referenced profile");
      store.profiles = store.profiles.filter((item) => item.name !== original);
      store.profiles.push(profile);
      if (original && original !== profile.name) {
        for (const item of store.profiles) {
          if (item.vision_image_profile === original) item.vision_image_profile = profile.name;
          if (item.audio_profile === original) item.audio_profile = profile.name;
          if (item.vision_video_profile === original) item.vision_video_profile = profile.name;
        }
        for (const key of ["approval", "metadata", "toolchain", "image", "audio", "video"] as const) if (store.references[key] === original) store.references[key] = profile.name;
        for (const session of store.sessions.values()) if (session.profileName === original) session.profileName = profile.name;
      }
      runtime.events.broadcast({ type: "llm_profile_changed", ...(original && original !== profile.name ? { operation: "renamed" as const, old_name: original, new_name: profile.name } : {}) });
      return jsonResponse({ profile, notification_failures: [] });
    }
    if (method === "DELETE") {
      const name = text(body.profile_name), replacement = body.replacement_profile_name === null ? null : text(body.replacement_profile_name);
      if (!store.profiles.some((item) => item.name === name)) throw new PreviewHttpError(404, "Profile does not exist");
      if (replacement === name || (replacement !== null && !store.profiles.some((item) => item.name === replacement))) throw new PreviewHttpError(422, "Invalid replacement profile");
      const incoming = store.profiles.some((item) => item.name !== name && [item.vision_image_profile, item.audio_profile, item.vision_video_profile].includes(name));
      if (incoming && replacement === null) throw new PreviewHttpError(409, "Choose a replacement for referenced profile");
      const switched: string[] = [];
      for (const session of store.sessions.values()) if (session.profileName === name) { session.profileName = replacement ?? ""; switched.push(session.info.id); }
      store.profiles = store.profiles.filter((item) => item.name !== name);
      for (const profile of store.profiles) {
        if (profile.vision_image_profile === name) profile.vision_image_profile = replacement;
        if (profile.audio_profile === name) profile.audio_profile = replacement;
        if (profile.vision_video_profile === name) profile.vision_video_profile = replacement;
      }
      for (const key of ["approval", "metadata", "toolchain", "image", "audio", "video"] as const) if (store.references[key] === name) store.references[key] = replacement;
      runtime.events.broadcast({ type: "llm_profile_changed", operation: "deleted", old_name: name, new_name: replacement });
      return jsonResponse({ deleted: true, profile_name: name, replacement_profile_name: replacement, switched_sessions: switched, pending_sessions: [], notification_failures: [] });
    }
    return null;
  }
  if (path === "/api/llm/clients" && method === "GET") return jsonResponse({ clients: [...new Set(store.profiles.map((item) => item.llm_client_name))] });
  const reference = path === "/api/approval/profile" ? "approval" : path === "/api/metadata/profile" ? "metadata" : path === "/api/toolchain-summary/profile" ? "toolchain" : null;
  if (reference) {
    if (method === "GET") return jsonResponse(store.profileState(store.references[reference]));
    if (method === "PUT") {
      const body = await readBody(request), name = body.profile_name === null ? null : text(body.profile_name);
      if (name !== null && !store.profiles.some((item) => item.name === name)) throw new PreviewHttpError(422, "Unknown profile");
      store.references[reference] = name;
      const state = store.profileState(name);
      if (reference === "approval") runtime.events.broadcast({ type: "approval_profile_changed", approval_profile_name: name, approval_profile_model: state.model, approval_profile_available: state.available });
      if (reference === "metadata") runtime.events.broadcast({ type: "metadata_profile_changed", metadata_profile_name: name, metadata_profile_model: state.model, metadata_profile_available: state.available });
      if (reference === "toolchain") runtime.events.broadcast({ type: "toolchain_summary_profile_changed", toolchain_summary_profile_name: name, toolchain_summary_profile_model: state.model, toolchain_summary_profile_available: state.available });
      return jsonResponse({ state });
    }
  }
  if (path === "/api/modality/profiles") {
    if (method === "GET") return jsonResponse({ image: store.profileState(store.references.image), audio: store.profileState(store.references.audio), video: store.profileState(store.references.video) });
    if (method === "PUT") {
      const body = await readBody(request);
      if (body.media_type !== "image" && body.media_type !== "audio" && body.media_type !== "video") throw new PreviewHttpError(422, "Unknown modality");
      const key: ModalityType = body.media_type;
      const name = body.profile_name === null ? null : text(body.profile_name);
      if (name !== null && !store.profiles.some((item) => item.name === name)) throw new PreviewHttpError(422, "Unknown profile");
      store.references[key] = name;
      const image = store.profileState(store.references.image), audio = store.profileState(store.references.audio), video = store.profileState(store.references.video);
      runtime.events.broadcast({ type: "modality_profile_changed", modality_vision_image_profile_name: image.profile_name, modality_vision_image_profile_model: image.model, modality_vision_image_profile_available: image.available,
        modality_audio_profile_name: audio.profile_name, modality_audio_profile_model: audio.model, modality_audio_profile_available: audio.available,
        modality_vision_video_profile_name: video.profile_name, modality_vision_video_profile_model: video.model, modality_vision_video_profile_available: video.available });
      return jsonResponse({ state: store.profileState(name) });
    }
  }
  if (path === "/api/agent-loop/settings" && (method === "GET" || method === "PUT")) {
    if (method === "PUT") { const value = (await readBody(request)).max_tool_turns; store.maxToolTurns = value === null ? null : integer(value, 1); }
    return jsonResponse({ max_tool_turns: store.maxToolTurns, effective_max_tool_turns: store.maxToolTurns ?? PREVIEW.defaultMaxTurns, default_max_tool_turns: PREVIEW.defaultMaxTurns });
  }
  if (path === "/api/characters/profiles" && method === "GET") return jsonResponse(createCharacterProfiles());
  if (path === "/api/characters/avatars" && method === "GET") return jsonResponse(createCharacterAvatars());
  if (path === "/api/activity/overview" && method === "GET") return jsonResponse({ ...ACTIVITY_OVERVIEW,
    session_count: store.sessions.size, active_loop_count: [...store.sessions.values()].filter((session) => session.activity !== null).length });
  if (path === "/api/skills/list" && method === "GET") return jsonResponse({ skills: [{ name: "research", description: labels.script.summary }, { name: "frontend", description: labels.script.title }] });
  if (path === "/api/sandbox-spaces/pick-directory" && method === "POST") return jsonResponse({ selected: true, path: "D:\\Projects\\demo" });
  if (path === "/api/sandbox-spaces") {
    if (method === "GET") return jsonResponse({ spaces: store.spaces });
    if (method === "POST") {
      const space = sandboxInput(await readBody(request));
      if (store.spaces.some((item) => item.name === space.name)) throw new PreviewHttpError(409, "Namespace already exists");
      store.spaces.push(space); return jsonResponse({ space });
    }
  }
  const spacePath = path.match(/^\/api\/sandbox-spaces\/([^/]+)$/);
  if (spacePath) {
    const name = decodeURIComponent(spacePath[1]), existing = store.spaces.find((item) => item.name === name);
    if (!existing) throw new PreviewHttpError(404, "Namespace does not exist");
    if (method === "DELETE") { store.spaces = store.spaces.filter((item) => item !== existing); return jsonResponse({ removed: true }); }
    if (method === "PUT") {
      const space = sandboxInput(await readBody(request));
      if (name !== space.name) throw new PreviewHttpError(422, "Namespace cannot be renamed");
      store.spaces = store.spaces.map((item) => item === existing ? space : item); return jsonResponse({ space });
    }
  }
  return null;
}
