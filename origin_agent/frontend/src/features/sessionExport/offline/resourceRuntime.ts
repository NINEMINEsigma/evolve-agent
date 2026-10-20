import type { OfflineExportData, OfflineAsset, ExportDocumentKind } from "../types";
import type { MessageResourceKind } from "../../../components/primitives/MessageRenderEnvironment";
import { extractDocumentDependencies } from "../documentDependencies";
import { EXPORT_LIMITS } from "../limits";

export interface OfflineFrameAsset { id: string; mime: string; base64: string }
export interface OfflineFramePayload { assets: OfflineFrameAsset[]; aliases: Record<string, string>; baseUrl: string }
export interface OfflineResourceRuntime {
  resolve(raw: string, kind: MessageResourceKind): string | null;
  assetRefFor(raw: string): string | null;
  assetOf(id: string): OfflineAsset | null;
  collectFrameAssets(refs: Iterable<string>, baseUrl?: string): OfflineFramePayload;
  dispose(): void;
}
export function offlineAssetBytes(asset: OfflineFrameAsset): Uint8Array {
  const binary = atob(asset.base64);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}
export function offlineAssetText(asset: OfflineFrameAsset): string {
  return new TextDecoder("utf-8", { fatal: true }).decode(offlineAssetBytes(asset));
}
export function canonicalizeExportRef(raw: string, baseUrl: string): string {
  const value = raw.trim();
  if (value.startsWith("export-asset:") || value.startsWith("data:")) return value;
  try {
    const url = new URL(value, baseUrl);
    url.hash = "";
    for (const key of ["visual_raw", "visual_probe", "visual_sid", "visual_kind"]) url.searchParams.delete(key);
    return url.href;
  } catch { return value; }
}
export function createOfflineAssetUrls(data: OfflineExportData): OfflineResourceRuntime {
  const byId = new Map(data.assets.map((asset) => [asset.id, asset]));
  const urls = new Map<string, string>();
  const find = (raw: string, base = data.originalBaseUrl): string | null => {
    const key = canonicalizeExportRef(raw, base);
    const id = data.aliases[key] || (key.startsWith("export-asset:") ? key.slice("export-asset:".length) : "");
    return byId.has(id) ? id : null;
  };
  return {
    resolve(raw: string, _kind: MessageResourceKind): string | null {
      // 只返回本次资源表生成的 URL；失效旧 blob/未归档 data 不能绕过预算。
      const id = find(raw);
      if (!id) return null;
      const asset = byId.get(id)!;
      if (!urls.has(id)) urls.set(id, URL.createObjectURL(new Blob([offlineAssetBytes(asset)], { type: asset.mime })));
      const hash = raw.startsWith("data:") || raw.startsWith("export-asset:") ? "" : new URL(raw, data.originalBaseUrl).hash;
      return urls.get(id)! + hash;
    },
    assetRefFor(raw: string): string | null { const id = find(raw); return id ? `export-asset:${id}` : null; },
    assetOf(id: string): OfflineAsset | null { return byId.get(id) || null; },
    collectFrameAssets(refs: Iterable<string>, baseUrl = data.originalBaseUrl): OfflineFramePayload {
      const ids = new Set<string>();
      const scanned = new Set<string>();
      const queue = Array.from(refs, (url) => ({ url, base: baseUrl, depth: 0 }));
      for (let index = 0; index < queue.length && index < EXPORT_LIMITS.resources * EXPORT_LIMITS.depth; index++) {
        const item = queue[index];
        const absolute = canonicalizeExportRef(item.url, item.base);
        const id = find(item.url, item.base);
        if (!id || item.depth > EXPORT_LIMITS.depth || scanned.has(absolute)) continue;
        scanned.add(absolute); ids.add(id);
        const asset = byId.get(id)!;
        let kind: ExportDocumentKind | null = null;
        if (asset.mime.includes("css")) kind = "css";
        else if (asset.mime.includes("javascript")) kind = "script";
        else if (asset.mime.includes("json")) kind = "json";
        else if (asset.mime.includes("html")) kind = "html";
        if (!kind) continue;
        try {
          const scan = extractDocumentDependencies(offlineAssetText(asset), kind === "script" ? item.base : absolute, kind);
          for (const child of scan.dependencies) queue.push({ url: child.url, base: child.baseUrl, depth: item.depth + 1 });
        } catch { /* 无法解析的文本仍保留字节，frame 内明确报告无法执行/读取。 */ }
      }
      const aliases: Record<string, string> = {};
      for (const [key, id] of Object.entries(data.aliases)) if (ids.has(id)) aliases[key] = id;
      return { assets: Array.from(ids, (id) => byId.get(id)!), aliases, baseUrl };
    },
    dispose(): void { for (const url of urls.values()) URL.revokeObjectURL(url); urls.clear(); },
  };
}
