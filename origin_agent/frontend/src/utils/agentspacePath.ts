import type { EntrySelection, FileEntry } from "../types";

export function normalizePath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  const parts: string[] = normalized ? normalized.split("/") : [];
  if (parts.some((part: string) => !part || part === "." || part === "..")) {
    throw new Error("路径包含无效段");
  }
  return parts.join("/");
}

export function joinPath(parent: string, name: string): string {
  const base = normalizePath(parent);
  const child = normalizePath(name);
  if (!child || child.includes("/")) throw new Error("名称不能包含路径分隔符");
  return base ? `${base}/${child}` : child;
}

export function parentPath(path: string): string {
  const normalized = normalizePath(path);
  const index = normalized.lastIndexOf("/");
  return index < 0 ? "" : normalized.slice(0, index);
}

export function baseName(path: string): string {
  const normalized = normalizePath(path);
  const index = normalized.lastIndexOf("/");
  return index < 0 ? normalized : normalized.slice(index + 1);
}

export function isPathWithin(path: string, parent: string): boolean {
  const normalizedPath = normalizePath(path);
  const normalizedParent = normalizePath(parent);
  return normalizedPath === normalizedParent || (
    normalizedParent === ""
      ? normalizedPath !== ""
      : normalizedPath.startsWith(`${normalizedParent}/`)
  );
}

export function rewritePathPrefix(path: string, oldPath: string, newPath: string): string {
  const normalized = normalizePath(path);
  const oldNormalized = normalizePath(oldPath);
  if (!isPathWithin(normalized, oldNormalized)) return normalized;
  const suffix = normalized.slice(oldNormalized.length).replace(/^\//, "");
  const prefix = normalizePath(newPath);
  return suffix ? `${prefix}/${suffix}` : prefix;
}

export function sortEntries(entries: FileEntry[]): FileEntry[] {
  return [...entries].sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === "dir" ? -1 : 1;
    const localized = left.name.localeCompare(right.name, undefined, {
      numeric: true,
      sensitivity: "base",
    });
    return localized || left.name.localeCompare(right.name);
  });
}

export function creationParentForSelection(selection: EntrySelection): string {
  if (!selection) return "";
  return selection.kind === "dir" ? selection.path : parentPath(selection.path);
}
