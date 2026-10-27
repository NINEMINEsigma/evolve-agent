import { PREVIEW } from "../constants";
import content from "../content/zh-CN.json";
import type { PreviewFile } from "../types";
import { createCharacterProfiles } from "./catalog";
import { createSeedSessions } from "./sessions";

export function createSeedFiles(): PreviewFile[] {
  const files: PreviewFile[] = [];
  const directories = new Set<string>();

  function addDirectory(path: string): void {
    if (path === "" || directories.has(path)) return;
    const separator = path.lastIndexOf("/");
    if (separator >= 0) addDirectory(path.slice(0, separator));
    directories.add(path);
    files.push({ path, kind: "dir", content: "" });
  }

  function addFile(path: string, text: string): void {
    const separator = path.lastIndexOf("/");
    if (separator >= 0) addDirectory(path.slice(0, separator));
    files.push({ path, kind: "file", content: text });
  }

  addDirectory(".trash");
  addDirectory("assets");
  addFile("README.md", content.files.readme);
  addFile("SOUL.md", "# Evolve Agent\n\nHelp turn clear goals into inspectable deliverables. This is a fictional preview profile.\n");
  addFile("reports/brief.md", content.files.brief);
  addFile("reports/checklist.md", content.files.checklist);
  addFile("reports/review.md", content.files.review);
  addFile("reports/review.log", "2026-10-27T02:30:00.000Z Review completed (fixed demonstration).\n");
  addFile("reports/locked.md", content.files.locked);
  addFile("notes/audience.md", content.files.audience);
  addFile("drafts/retired/outline.md", content.files.draft);
  addFile("assets/cover.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540"><rect width="960" height="540" rx="24" fill="#101b24"/><circle cx="740" cy="160" r="105" fill="#173d42"/><text x="72" y="248" fill="#d7f5ed" font-family="sans-serif" font-size="52">Evolve Agent</text><text x="76" y="308" fill="#8ab7b2" font-family="sans-serif" font-size="24">From clear goals to visible results.</text></svg>\n');

  for (const character of createCharacterProfiles().characters) {
    const path = character.profile_path.slice("ws:".length);
    addFile(path, `${character.system_prompt}\n`);
    addFile(`${path}.meta`, [
      "[llm_profile]", character.llm_profile_name,
      "[description]", character.description,
    ].join("\n") + "\n");
  }

  // 虚拟文件与变量 Tab 从同一份固定种子派生，不引入运行体依赖。
  for (const session of createSeedSessions()) {
    if (!session.variables.root_exists) continue;
    addDirectory(session.variables.directory_path.slice("ws:".length));
    for (const variable of session.variables.variables) {
      if (variable.raw_value === null) continue;
      addFile(variable.path.slice("ws:".length), `${variable.raw_value}\n`);
      if (variable.raw_metadata !== null) {
        const metadata = Object.entries(variable.raw_metadata)
          .map(([key, value]) => `[${key}]\n${value}`)
          .join("\n");
        addFile(variable.metadata_path.slice("ws:".length), `${metadata}\n`);
      }
    }
  }

  addFile("preview.json", JSON.stringify({
    version: PREVIEW.version, session: PREVIEW.mainSession,
    persistence: "memory-only", contains_real_data: false,
  }, null, 2) + "\n");
  return files;
}
