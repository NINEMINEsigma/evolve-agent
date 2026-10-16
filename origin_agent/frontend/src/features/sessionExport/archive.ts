import { zip, strToU8 } from "fflate";
import type { OfflineExportData, ExportCollection, SessionExportSnapshotDto } from "./types";
import { EXPORT_CSP, EXPORT_DATA_ID, EXPORT_LIMITS, EXPORT_VIEWER_PREFIX } from "./limits";
import { fetchExportResponse } from "./api";
import { exportLabels } from "./labels";

export interface OfflineDocumentInput { data: OfflineExportData; signal: AbortSignal }
export interface OfflineArchiveInput extends OfflineDocumentInput {}
export function bytesToBase64(bytes: Uint8Array): string {
  let value = "";
  const blockSize = 0x8000;
  for (let index = 0; index < bytes.length; index += blockSize) {
    value += String.fromCharCode(...bytes.subarray(index, index + blockSize));
  }
  return btoa(value);
}
function escapeText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
export function serializeExportData(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}
export function makeOfflineData(
  snapshot: SessionExportSnapshotDto, collection: ExportCollection,
  preferences: { stagePaused: boolean; chatStylePaused: boolean },
): OfflineExportData {
  // 仅替换精确的已识别媒体值；普通正文中的裸 Base64 不作猜测。
  const usedDataUrls = new Set<string>();
  const dataKeys = Object.keys(collection.aliases).filter((key) => key.startsWith("data:"));
  const json = JSON.stringify(snapshot, (_key, value: unknown) => {
    if (typeof value !== "string") return value;
    if (value.startsWith("data:") && collection.aliases[value]) return `export-asset:${collection.aliases[value]}`;
    for (const key of dataKeys) {
      if (value.includes(key)) usedDataUrls.add(key);
    }
    return value;
  });
  const aliases: Record<string, string> = {};
  for (const [key, value] of Object.entries(collection.aliases)) {
    if (!key.startsWith("data:") || usedDataUrls.has(key)) aliases[key] = value;
  }
  return {
    formatVersion: 1, snapshot: JSON.parse(json) as SessionExportSnapshotDto,
    assets: collection.assets.map((asset) => ({ id: asset.id, mime: asset.mime, digest: asset.digest, base64: bytesToBase64(asset.bytes) })),
    aliases, issues: collection.issues, visualEntries: collection.visualEntries,
    originalBaseUrl: window.location.href, ...preferences,
  };
}
export async function buildOfflineDocument({ data, signal }: OfflineDocumentInput): Promise<string> {
  const [js, css] = await Promise.all(["viewer.js", "viewer.css"].map((name) => fetchExportResponse(
    `${EXPORT_VIEWER_PREFIX}/${name}`, {}, signal, EXPORT_LIMITS.viewerBytes,
  )));
  if (!js.response.ok || !css.response.ok) throw new Error("Offline viewer build is unavailable");
  if (js.bytes.byteLength + css.bytes.byteLength > EXPORT_LIMITS.viewerBytes) throw new Error("Viewer byte limit exceeded");
  const stylesheet = new TextDecoder("utf-8", { fatal: true }).decode(css.bytes).replace(/<\/style/gi, "<\\/style");
  const bundle = bytesToBase64(js.bytes);
  const bootstrap = `(function(){var raw=atob(${JSON.stringify(bundle)}),bytes=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);var url=URL.createObjectURL(new Blob([bytes],{type:'text/javascript'}));var script=document.createElement('script');script.src=url;script.onload=function(){URL.revokeObjectURL(url)};script.onerror=function(){URL.revokeObjectURL(url);document.getElementById('root').textContent='Offline viewer failed to load'};document.body.appendChild(script)})();`;
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${escapeText(EXPORT_CSP)}"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escapeText(data.snapshot.title || data.snapshot.session_id)}</title><style>${stylesheet}</style></head><body><div id="root">${escapeText(exportLabels.offline)}</div><script type="application/json" id="${EXPORT_DATA_ID}">${serializeExportData(data)}</script><script>${bootstrap}</script></body></html>`;
  if (signal.aborted) throw signal.reason;
  const max = Math.min(EXPORT_LIMITS.archiveInputBytes, data.snapshot.limits.max_archive_input_bytes);
  if (new TextEncoder().encode(html).byteLength > max) throw new Error("Offline HTML byte limit exceeded");
  return html;
}
export async function buildSessionExportArchive(input: OfflineArchiveInput, signal: AbortSignal): Promise<Blob> {
  const html = await buildOfflineDocument(input);
  if (signal.aborted) throw signal.reason;
  const manifest = {
    format_version: 1, session_id: input.data.snapshot.session_id,
    captured_at: input.data.snapshot.captured_at, history_count: input.data.snapshot.history_count,
    row_count: input.data.snapshot.rows.length,
    resources: input.data.assets.map((asset) => ({ id: asset.id, mime: asset.mime, digest: asset.digest })),
    issues: input.data.issues.map((issue) => ({ owner: issue.owner, code: issue.code })),
    limitations: exportLabels.limitations,
  };
  const files = { "index.html": strToU8(html), "manifest.json": strToU8(JSON.stringify(manifest, null, 2)), "README.txt": strToU8(exportLabels.readme) };
  const size = Object.values(files).reduce((sum, value) => sum + value.byteLength, 0);
  if (size > Math.min(EXPORT_LIMITS.archiveInputBytes, input.data.snapshot.limits.max_archive_input_bytes)) throw new Error("Archive input byte limit exceeded");
  return new Promise<Blob>((resolve, reject) => {
    let settled = false;
    const abort = () => { if (!settled) { settled = true; terminate(); reject(signal.reason || new DOMException("Export cancelled", "AbortError")); } };
    const terminate = zip(files, { level: 1 }, (error, bytes) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve(new Blob([bytes], { type: "application/zip" }));
    });
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}
