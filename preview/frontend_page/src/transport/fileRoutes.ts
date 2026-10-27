import type { AgentspaceEvent, FileEntry, TrashEntry } from "@origin/types";
import type { PreviewRuntime } from "../types";
import { PREVIEW, DEMO_ASSETS } from "../constants";
import { PreviewHttpError, PreviewResourceResponse, jsonResponse, readBody, text } from "./contracts";
import labels from "../content/zh-CN.json";

function changed(runtime: PreviewRuntime, kind: AgentspaceEvent["kind"], path: string | null, newPath: string | null = null, operationId: string | null = null): void {
  runtime.events.agentspace({ sequence: Number(runtime.store.nextId("event").split("-").pop()), kind, source: "service", path,
    new_path: newPath, is_directory: path ? runtime.store.files.get(newPath ?? path)?.kind === "dir" : null,
    locks: null, timestamp: PREVIEW.timestamp, operation_id: operationId, version: null, message: null });
}
function entry(runtime: PreviewRuntime, path: string): FileEntry {
  const file = runtime.store.files.get(path);
  if (!file) throw new PreviewHttpError(404, "Virtual entry does not exist");
  return { path, name: path.split("/").pop() || "", kind: file.kind };
}
export async function handleFileRequest(request: Request, runtime: PreviewRuntime): Promise<Response | null> {
  const url = new URL(request.url), route = url.pathname, method = request.method, store = runtime.store;
  const visual = route.match(/^\/files\/ws\/sessions\/([^/]+)\/(site\/index\.html|stage\/index\.html|chat-style\/index\.css)$/);
  if (visual) {
    if (method !== "HEAD") return null;
    const session = store.session(decodeURIComponent(visual[1]));
    const kind = visual[2].startsWith("site/") ? "site" : visual[2].startsWith("stage/") ? "stage" : "chatStyle";
    const exists = kind === "site" ? session.rows.length > 0 : runtime.options.scene === "visual";
    if (!exists) return new Response(null, { status: 404 });
    return new PreviewResourceResponse(null, { status: 200, headers: { "X-Session-Visual-Version": PREVIEW.version,
      "Content-Type": kind === "chatStyle" ? "text/css" : "text/html" } }, new URL(DEMO_ASSETS[kind], location.origin).href);
  }
  if (route === "/api/file-picker" && method === "POST") return jsonResponse({ uploaded: true, files: [{ filename: labels.ui.filePickerName, size: 2048, method: "copy" }] });
  if (!route.startsWith("/api/agentspace/")) return null;
  const suffix = route.slice("/api/agentspace/".length);
  if (method === "GET") {
    if (suffix === "list") {
      const path = store.filePath(url.searchParams.get("path") ?? "");
      if (path && store.files.get(path)?.kind !== "dir") throw new PreviewHttpError(404, "Virtual directory does not exist");
      const prefix = path ? `${path}/` : "";
      const entries = [...store.files.values()].filter((file) => file.path.startsWith(prefix) && file.path !== path && !file.path.slice(prefix.length).includes("/"))
        .sort((a, b) => Number(b.kind === "dir") - Number(a.kind === "dir") || a.path.localeCompare(b.path, "en", { numeric: true }))
        .map((file) => ({ ...entry(runtime, file.path), type: file.kind }));
      return jsonResponse({ entries });
    }
    if (suffix === "read") return jsonResponse(await store.snapshot(url.searchParams.get("path") ?? ""));
    if (suffix === "trash") return jsonResponse({ entries: [...store.trash.values()].map((item) => item.entry) });
    if (suffix === "locks") return jsonResponse({ locks: store.locks });
  }
  if (method === "POST") {
    const body = await readBody(request);
    const operationId = body.operation_id === undefined ? store.nextId("operation") : text(body.operation_id);
    if (["write", "mkdir", "rename", "delete"].includes(suffix)) {
      const path = store.filePath(text(body.path));
      if (!path) throw new PreviewHttpError(422, "Cannot change the virtual root");
      if (store.locks.some((lock) => lock.path === path || (lock.recursive && path.startsWith(`${lock.path}/`)))) throw new PreviewHttpError(409, "Virtual file is locked");
      const parent = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
      if (parent && store.files.get(parent)?.kind !== "dir") throw new PreviewHttpError(404, "Virtual parent does not exist");
      const existing = store.files.get(path);
      if (suffix === "write") {
        if (existing?.kind === "dir") throw new PreviewHttpError(409, "Target is a directory");
        const current = existing ? await store.snapshot(path) : null;
        if ((current?.version ?? null) !== body.expected_version) throw new PreviewHttpError(409, "Virtual file version changed");
        const content = text(body.content).replace(/\r\n?/g, "\n"); request.signal.throwIfAborted();
        store.files.set(path, { path, content, kind: "file" });
        changed(runtime, existing ? "modified" : "created", path, null, operationId);
        return jsonResponse({ ...await store.snapshot(path), operation_id: operationId });
      }
      if (suffix === "mkdir") {
        if (existing) throw new PreviewHttpError(409, "Virtual path already exists");
        store.files.set(path, { path, kind: "dir", content: "" }); changed(runtime, "created", path, null, operationId);
        return jsonResponse({ entry: entry(runtime, path) });
      }
      if (!existing) throw new PreviewHttpError(404, "Virtual path does not exist");
      if (suffix === "rename") {
        const name = text(body.new_name);
        if (!name || /[/\\:]/.test(name) || name === "." || name === "..") throw new PreviewHttpError(422, "Invalid file name");
        const destination = parent ? `${parent}/${name}` : name;
        if (store.files.has(destination)) throw new PreviewHttpError(409, "Virtual destination already exists");
        for (const file of [...store.files.values()]) if (file.path === path || file.path.startsWith(`${path}/`)) {
          store.files.delete(file.path); const nextPath = destination + file.path.slice(path.length);
          store.files.set(nextPath, { ...file, path: nextPath });
        }
        changed(runtime, "moved", path, destination, operationId);
        return jsonResponse({ old_path: path, new_path: destination, operation_id: operationId });
      }
      const files = [...store.files.values()].filter((file) => file.path === path || file.path.startsWith(`${path}/`));
      const trashEntry: TrashEntry = { entry_id: store.nextId("trash"), state: "ready", original_path: path,
        name: path.split("/").pop() ?? path, kind: existing.kind, deleted_at: PREVIEW.timestamp,
        size: files.reduce((sum, file) => sum + new TextEncoder().encode(file.content).length, 0), error: null };
      store.trash.set(trashEntry.entry_id, { entry: trashEntry, files });
      for (const file of files) store.files.delete(file.path);
      changed(runtime, "deleted", path, null, operationId); changed(runtime, "trash_changed", null, null, operationId);
      return jsonResponse({ entry: trashEntry });
    }
    const restore = suffix.match(/^trash\/([^/]+)\/restore$/);
    if (restore) {
      const id = decodeURIComponent(restore[1]), item = store.trash.get(id);
      if (!item?.entry.original_path) throw new PreviewHttpError(404, "Trash entry does not exist");
      const original = item.entry.original_path;
      let destination = original, count = 0;
      while (store.files.has(destination)) destination = `${original}.restored-${++count}`;
      for (const file of item.files) { const path = destination + file.path.slice(original.length); store.files.set(path, { ...file, path }); }
      store.trash.delete(id); changed(runtime, "created", destination, null, operationId); changed(runtime, "trash_changed", null, null, operationId);
      return jsonResponse({ entry: item.entry, restored_path: destination, operation_id: operationId });
    }
  }
  if (method === "DELETE") {
    if (suffix === "trash") { const count = store.trash.size; store.trash.clear(); changed(runtime, "trash_changed", null); return jsonResponse({ deleted: count, failures: [] }); }
    const purge = suffix.match(/^trash\/([^/]+)$/);
    if (purge) {
      if (!store.trash.delete(decodeURIComponent(purge[1]))) throw new PreviewHttpError(404, "Trash entry does not exist");
      changed(runtime, "trash_changed", null); return jsonResponse(null);
    }
  }
  return null;
}
