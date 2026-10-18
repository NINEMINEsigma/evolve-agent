import type { SessionFileChangeEntryDto } from "./types";

export interface FileChangeTreeNode {
  key: string;
  name: string;
  path: string;
  directory: boolean;
  entry: SessionFileChangeEntryDto | null;
  children: FileChangeTreeNode[];
}

function compareNodes(left: FileChangeTreeNode, right: FileChangeTreeNode): number {
  if (left.directory !== right.directory) return left.directory ? -1 : 1;
  return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
}

function directoryNode(key: string, name: string, path: string): FileChangeTreeNode {
  return { key, name, path, directory: true, entry: null, children: [] };
}

export function buildFileChangeTree(entries: readonly SessionFileChangeEntryDto[]): FileChangeTreeNode[] {
  const roots: FileChangeTreeNode[] = [];
  const directories = new Map<string, FileChangeTreeNode>();
  const findOrCreate = (
    list: FileChangeTreeNode[], key: string, name: string, path: string,
  ): FileChangeTreeNode => {
    const existing = directories.get(key);
    if (existing !== undefined) return existing;
    const created = directoryNode(key, name, path);
    list.push(created);
    directories.set(key, created);
    return created;
  };

  for (const entry of entries) {
    if (entry.display_state === "deleted" && entry.created_by_session) continue;
    const separator = entry.path.indexOf(":");
    const namespace = entry.path.slice(0, separator + 1);
    const relative = entry.path.slice(separator + 1);
    const segments = relative ? relative.split("/") : [];
    const namespaceRoot = findOrCreate(roots, namespace, namespace, namespace);
    let list = namespaceRoot.children;
    let parentKey = namespace;
    let parentPath = namespace;
    const folderSegments = segments.slice(0, -1);
    for (const segment of folderSegments) {
      const key = `${parentKey}/${segment}`;
      const path = `${parentPath}${parentPath.endsWith(":") ? "" : "/"}${segment}`;
      const node = findOrCreate(list, key, segment, path);
      list = node.children;
      parentKey = key;
      parentPath = path;
    }
    const name = segments.length > 0 ? segments[segments.length - 1] : namespace;
    if (entry.kind === "directory") {
      const key = `${parentKey}/${name}`;
      const path = `${parentPath}${parentPath.endsWith(":") ? "" : "/"}${name}`;
      const node = findOrCreate(list, key, name, path);
      node.entry = entry;
      continue;
    }
    list.push({
      key: entry.path,
      name,
      path: entry.path,
      directory: false,
      entry,
      children: [],
    });
  }

  const sort = (nodes: FileChangeTreeNode[]) => {
    nodes.sort(compareNodes);
    for (const node of nodes) if (node.directory) sort(node.children);
  };
  sort(roots);
  return roots;
}
