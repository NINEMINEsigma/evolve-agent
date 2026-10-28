import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { Plugin } from "vite";

export const previewRoot = fileURLToPath(new URL("../", import.meta.url));
export const sourceRoot = path.resolve(previewRoot, "../../origin_agent/frontend/src");
export const iconPath = path.resolve(sourceRoot, "../public/icon.ico");
const marker = "?preview-original";
const sourceModules = {
  storage: "constants/storage.ts",
  "media-api": "features/sessionMedia/api.ts",
  "session-site": "hooks/useSessionSite.ts",
  "audio-recorder": "hooks/useAudioRecorder.ts",
  "session-export": "features/sessionExport/useSessionExport.ts",
} as const;
const adapters = {
  storage: "storage.ts", "media-api": "mediaApi.ts", "session-site": "sessionSite.ts",
  "audio-recorder": "audioRecorder.ts", "session-export": "sessionExport.ts",
} as const;
const normalize = (value: string) => value.replace(/\\/g, "/").toLowerCase();
const clean = (value: string) => value.split("?")[0];

export function createSourceBridge(): Plugin {
  const replacements = new Map(Object.entries(sourceModules).map(([key, file]) => [
    normalize(path.resolve(sourceRoot, file)),
    path.resolve(previewRoot, "src/adapters", adapters[key as keyof typeof adapters]),
  ]));
  let dependencies = new Set<string>();
  return {
    name: "preview-source-bridge",
    enforce: "pre",
    async configResolved() {
      const manifest = JSON.parse(await readFile(path.resolve(previewRoot, "package.json"), "utf8")) as {
        dependencies: Record<string, string>; devDependencies: Record<string, string>;
      };
      dependencies = new Set([...Object.keys(manifest.dependencies), ...Object.keys(manifest.devDependencies)]);
    },
    async resolveId(id, importer, options) {
      if (id.startsWith("\0")) return null;
      if (id.startsWith("@preview-original/")) {
        const key = id.slice("@preview-original/".length) as keyof typeof sourceModules;
        if (!(key in sourceModules)) throw new Error(`Unknown original source alias: ${id}`);
        return path.resolve(sourceRoot, sourceModules[key]) + marker;
      }
      if (id.includes(marker)) return null;
      const actualImporter = importer?.replace(marker, "");
      let candidate = id;
      if (id.startsWith("@origin/")) candidate = path.resolve(sourceRoot, id.slice("@origin/".length));
      const parts = id.split("/");
      const packageName = id.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
      // 用预览入口作解析起点；不要求origin或宿主根安装任何包。
      const anchor = dependencies.has(packageName)
        ? path.resolve(previewRoot, "index.html") : actualImporter;
      const resolved = await this.resolve(candidate, anchor, { ...options, skipSelf: true });
      if (!resolved) return null;
      const replacement = replacements.get(normalize(clean(resolved.id)));
      if (replacement && !resolved.id.includes("?")) return replacement;
      return resolved;
    },
    async load(id) {
      if (!id.endsWith(marker)) return null;
      const file = id.slice(0, -marker.length);
      if (!Object.values(sourceModules).some((relative) => normalize(path.resolve(sourceRoot, relative)) === normalize(file))) {
        throw new Error("Original source bypass is outside the registered modules");
      }
      return readFile(file, "utf8");
    },
  };
}
