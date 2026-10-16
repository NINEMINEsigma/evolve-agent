import type {
  ExportAsset, ExportCollection, ExportCollectOptions, ExportDependency,
  ExportResourceClient, ExportResourceSource, SessionExportSnapshotDto,
} from "./types";
import { EXPORT_LIMITS } from "./limits";
import { sha256Hex } from "../../utils/sha256";
import { extractDocumentDependencies, extractMessageDependencies, sourceFileUrl } from "./documentDependencies";

export type ExportSourceResolution =
  | { kind: "inline"; url: string }
  | { kind: "file"; url: string; source: ExportResourceSource }
  | { kind: "unavailable"; url: string; code: string };
export function normalizeExportSource(raw: string, baseUrl: string, sessionId: string, origin = window.location.origin): ExportSourceResolution {
  if (raw.startsWith("data:")) return { kind: "inline", url: raw };
  if (!raw || raw.startsWith("#")) return { kind: "unavailable", url: raw, code: "fragment_reference" };
  if (/(?:^|[\/\\])(?:\.{2}|%2e(?:%2e|\.)|\.%2e)(?:[\/\\?#]|$)|%00|\x00/i.test(raw)) return { kind: "unavailable", url: raw, code: "invalid_resource_path" };
  let url: URL;
  try { url = new URL(raw, baseUrl); } catch { return { kind: "unavailable", url: raw, code: "invalid_resource_url" }; }
  url.hash = "";
  if (url.origin !== origin || !["http:", "https:"].includes(url.protocol) || url.username || url.password) return { kind: "unavailable", url: url.href, code: "external_resource" };
  const query = url.searchParams;
  const allowed = new Set(["visual_raw", "visual_probe", "visual_sid", "visual_kind"]);
  if (Array.from(query.keys()).some((key) => !allowed.has(key) || query.getAll(key).length !== 1)
    || (query.has("visual_raw") && query.get("visual_raw") !== "1")
    || (["visual_probe", "visual_sid", "visual_kind"].some((key) => query.has(key)) && (
      query.get("visual_probe") !== "1" || query.get("visual_sid") !== sessionId || !["stage", "chat_style"].includes(query.get("visual_kind") || "")
    ))) return { kind: "unavailable", url: url.href, code: "unsupported_query" };
  url.search = "";
  let parts: string[];
  try { parts = url.pathname.split("/").map(decodeURIComponent); } catch { return { kind: "unavailable", url: url.href, code: "invalid_resource_path" }; }
  if (parts.some((part) => part === ".." || part.includes("\0") || part.includes("\\") || part.includes("/") || /%2e|%2f|%5c/i.test(part))) return { kind: "unavailable", url: url.href, code: "invalid_resource_path" };
  if (["files", "downloads"].includes(parts[1]) && parts[2] && parts.length > 3 && !parts[2].includes(":")) {
    return { kind: "file", url: url.href, source: { kind: "sandbox", path: `${parts[2]}:${parts.slice(3).join("/")}` } };
  }
  if (parts[1] === "local-font" && parts.length > 2) return { kind: "file", url: url.href, source: { kind: "local_font", path: parts.slice(2).join("/") } };
  return { kind: "unavailable", url: url.href, code: "unsupported_resource_route" };
}
function inlineBytes(url: string, limit: number): { bytes: Uint8Array; mime: string } {
  const comma = url.indexOf(",");
  if (comma < 0) throw new Error("Invalid inline resource");
  const metadata = url.slice(5, comma);
  const mime = metadata.split(";")[0].toLowerCase() || "text/plain";
  if (!/^(?:image|audio|video|font)\/[a-z0-9.+-]+$|^(?:text\/(?:css|plain|javascript)|application\/(?:json|javascript|octet-stream|font-woff))$/.test(mime)) throw new Error("Unsupported inline MIME");
  const payload = url.slice(comma + 1);
  if (metadata.toLowerCase().endsWith(";base64")) {
    if (Math.ceil(payload.length * 3 / 4) > limit + 2) throw new Error("Inline resource exceeds limit");
    const raw = atob(payload);
    if (raw.length > limit) throw new Error("Inline resource exceeds limit");
    return { bytes: Uint8Array.from(raw, (char) => char.charCodeAt(0)), mime };
  }
  if (payload.length > limit * 3) throw new Error("Inline resource exceeds limit");
  const bytes = new TextEncoder().encode(decodeURIComponent(payload));
  if (bytes.byteLength > limit) throw new Error("Inline resource exceeds limit");
  return { bytes, mime };
}
export async function collectExportResources(
  snapshot: SessionExportSnapshotDto, client: ExportResourceClient, options: ExportCollectOptions,
): Promise<ExportCollection> {
  const { signal, baseUrl, onProgress } = options;
  const collection: ExportCollection = { assets: [], aliases: {}, proofs: [], issues: [], visualEntries: {} };
  const scan = extractMessageDependencies(snapshot.rows, baseUrl);
  collection.issues.push(...scan.issues);
  const queue: ExportDependency[] = [...scan.dependencies];
  const maxBytes = Math.min(snapshot.limits.max_resource_bytes, EXPORT_LIMITS.resourceBytes);
  const maxTotal = Math.min(snapshot.limits.max_resource_total_bytes, EXPORT_LIMITS.resourceTotalBytes);
  const maxCount = Math.min(snapshot.limits.max_resources, EXPORT_LIMITS.resources);
  const maxDepth = Math.min(snapshot.limits.max_depth, EXPORT_LIMITS.depth);
  for (const visual of snapshot.visuals) {
    if (!visual.configured) continue;
    if (visual.error_code) collection.issues.push({ owner: visual.kind, source: visual.source_path, code: visual.error_code });
    if (visual.status !== "ready" || !visual.entry_path) {
      collection.issues.push({ owner: visual.kind, source: visual.source_path, code: visual.availability }); continue;
    }
    const url = sourceFileUrl(visual.entry_path, baseUrl);
    collection.visualEntries[visual.kind] = url;
    queue.push({ url, baseUrl: url, kind: visual.kind === "stage" ? "html" : "css", owner: visual.kind, depth: 0 });
  }
  let cursor = 0;
  let completed = 0;
  let totalBytes = 0;
  let attempted = 0;
  const scanned = new Set<string>();
  const loaded = new Map<string, Promise<ExportAsset | null>>();
  const byDigest = new Map<string, ExportAsset>();
  const check = () => { if (signal.aborted) throw signal.reason || new DOMException("Export cancelled", "AbortError"); };
  const addIssue = (dependency: ExportDependency, code: string) => collection.issues.push({
    owner: dependency.owner,
    source: dependency.url.startsWith("data:") ? dependency.url.slice(0, 120) + " [inline payload omitted]" : dependency.url,
    code,
  });
  const progress = () => onProgress({ completed, total: queue.length, bytes: totalBytes, issues: collection.issues.length });
  const load = async (dependency: ExportDependency, resolved: ExportSourceResolution): Promise<ExportAsset | null> => {
    check();
    if (resolved.kind === "unavailable") { addIssue(dependency, resolved.code); return null; }
    if (++attempted > maxCount) { addIssue(dependency, "resource_count_limit"); return null; }
    let bytes: Uint8Array;
    let mime: string;
    if (resolved.kind === "inline") {
      try { ({ bytes, mime } = inlineBytes(resolved.url, maxBytes)); }
      catch { addIssue(dependency, "invalid_or_large_inline_resource"); return null; }
    } else {
      const response = await client.read(resolved.source, signal);
      check();
      if (response.proof) collection.proofs.push(response.proof);
      if (response.status !== "saved") { addIssue(dependency, response.code); return null; }
      bytes = response.bytes; mime = response.mime.split(";")[0].trim();
    }
    if (bytes.byteLength > maxBytes) { addIssue(dependency, "resource_size_limit"); return null; }
    const hash = await sha256Hex(bytes);
    check();
    const identity = `${mime}:${hash}`;
    let asset = byDigest.get(identity);
    if (!asset) {
      if (totalBytes + bytes.byteLength > maxTotal) { addIssue(dependency, "resource_total_limit"); return null; }
      totalBytes += bytes.byteLength;
      asset = { id: `asset-${collection.assets.length}`, sourceKey: resolved.url, bytes, mime, digest: hash };
      collection.assets.push(asset); byDigest.set(identity, asset);
    }
    collection.aliases[resolved.url] = asset.id;
    collection.aliases[`export-asset:${asset.id}`] = asset.id;
    return asset;
  };
  const worker = async () => {
    while (cursor < queue.length) {
      check();
      const dependency = queue[cursor++];
      if (dependency.depth > maxDepth) { addIssue(dependency, "dependency_depth_limit"); completed++; progress(); continue; }
      const resolved = normalizeExportSource(dependency.url, dependency.baseUrl, snapshot.session_id, new URL(baseUrl).origin);
      const key = resolved.kind === "file" ? `${resolved.source.kind}:${resolved.source.path}` : resolved.url;
      const scanKey = `${key}:${dependency.kind}`;
      if (scanned.has(scanKey)) { completed++; progress(); continue; }
      scanned.add(scanKey);
      let pending = loaded.get(key);
      if (!pending) { pending = load(dependency, resolved); loaded.set(key, pending); }
      const asset = await pending;
      check();
      if (asset && resolved.kind !== "unavailable") {
        collection.aliases[resolved.url] = asset.id;
        if (dependency.kind !== "media") {
          const text = new TextDecoder().decode(asset.bytes);
          const childScan = extractDocumentDependencies(text, dependency.kind === "script" ? dependency.baseUrl : resolved.url, dependency.kind);
          collection.issues.push(...childScan.issues.map((issue) => ({ ...issue, owner: dependency.owner })));
          for (const child of childScan.dependencies) {
            if (dependency.owner === "chat_style" && child.kind === "css") {
              addIssue(dependency, "chat_style_import_forbidden"); continue;
            }
            if (queue.length >= maxCount * maxDepth) { addIssue(dependency, "dependency_scan_limit"); break; }
            queue.push({ ...child, depth: dependency.depth + 1, owner: dependency.owner });
          }
        }
      } else if (resolved.kind !== "unavailable") addIssue(dependency, "resource_unavailable");
      completed++; progress();
    }
  };
  await Promise.all(Array.from({ length: EXPORT_LIMITS.concurrency }, worker));
  check();
  for (const kind of ["stage", "chat_style"] as const) {
    const url = collection.visualEntries[kind];
    if (url && !collection.aliases[url]) {
      delete collection.visualEntries[kind];
      collection.issues.push({ owner: kind, source: url, code: "visual_entry_unavailable" });
    }
  }
  return collection;
}
