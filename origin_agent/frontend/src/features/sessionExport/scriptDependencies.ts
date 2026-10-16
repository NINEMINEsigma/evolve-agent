import { parse } from "acorn";
import { full } from "acorn-walk";
import type { Node } from "acorn";
import type { ExportDependencyScan } from "./types";
import { EXPORT_LIMITS } from "./limits";

interface ScriptNode extends Node {
  value?: unknown;
  name?: string;
  callee?: ScriptNode;
  object?: ScriptNode;
  property?: ScriptNode;
  computed?: boolean;
  arguments?: ScriptNode[];
  left?: ScriptNode;
  right?: ScriptNode;
}
function literal(node: ScriptNode | undefined): string | null {
  return node?.type === "Literal" && typeof node.value === "string" ? node.value : null;
}
function name(node: ScriptNode | undefined): string | null {
  if (node?.type === "Identifier") return node.name || null;
  if (node?.type === "MemberExpression" && !node.computed) return name(node.property);
  return null;
}
export function rewriteScriptResources(source: string, resolve: (raw: string) => string | null): string {
  const tree = parse(source, { ecmaVersion: "latest", sourceType: "script", allowHashBang: true });
  const edits: Array<{ start: number; end: number; value: string }> = [];
  full(tree, (raw) => {
    const node = raw as ScriptNode;
    let target: ScriptNode | undefined;
    if (node.type === "NewExpression" && ["URL", "Audio"].includes(name(node.callee) || "")) target = node.arguments?.[0];
    if (node.type === "AssignmentExpression" && node.left?.type === "MemberExpression" && ["src", "poster"].includes(name(node.left) || "")) target = node.right;
    if (node.type === "CallExpression" && name(node.callee) === "setAttribute" && ["src", "poster"].includes(literal(node.arguments?.[0]) || "")) target = node.arguments?.[1];
    const url = literal(target);
    const local = url ? resolve(url) : null;
    if (target && local) edits.push({ start: target.start, end: target.end, value: JSON.stringify(local) });
  });
  let result = source;
  for (const edit of edits.sort((left, right) => right.start - left.start)) result = result.slice(0, edit.start) + edit.value + result.slice(edit.end);
  return result;
}

export function extractScriptDependencies(source: string, baseUrl: string): ExportDependencyScan {
  const dependencies: ExportDependencyScan["dependencies"] = [];
  const issues: ExportDependencyScan["issues"] = [];
  const issue = (code: string) => {
    if (!issues.some((item) => item.code === code)) issues.push({ owner: baseUrl, source: baseUrl, code });
  };
  if (new TextEncoder().encode(source).byteLength > EXPORT_LIMITS.scriptBytes) {
    issue("script_scan_limit"); return { dependencies, issues };
  }
  try {
    const tree = parse(source, { ecmaVersion: "latest", sourceType: "script", allowHashBang: true });
    full(tree, (raw) => {
      const node = raw as ScriptNode;
      if (node.type === "ImportExpression" || node.type.startsWith("Import") || node.type.startsWith("Export")) issue("unsupported_script_capability");
      if (node.type === "CallExpression" || node.type === "NewExpression") {
        const callName = name(node.callee);
        if (["eval", "Function", "Worker", "SharedWorker", "WebSocket", "EventSource", "XMLHttpRequest", "WebTransport", "RTCPeerConnection", "webkitRTCPeerConnection", "importScripts", "sendBeacon", "write", "writeln", "register"].includes(callName || "")) issue("unsupported_script_capability");
        if (callName === "fetch" || (node.type === "NewExpression" && ["URL", "Audio"].includes(callName || ""))) {
          const url = literal(node.arguments?.[0]);
          if (url) dependencies.push({ url, baseUrl, kind: callName === "fetch" ? "json" : "media", owner: baseUrl, depth: 0 });
          else issue("dynamic_dependency");
        }
        if (callName === "setAttribute" && ["src", "poster"].includes(literal(node.arguments?.[0]) || "")) {
          const url = literal(node.arguments?.[1]);
          if (url) dependencies.push({ url, baseUrl, kind: "media", owner: baseUrl, depth: 0 });
          else issue("dynamic_dependency");
        }
      }
      if (node.type === "AssignmentExpression" && node.left?.type === "MemberExpression" && ["src", "poster"].includes(name(node.left) || "")) {
        const url = literal(node.right);
        if (url) dependencies.push({ url, baseUrl, kind: "media", owner: baseUrl, depth: 0 });
        else issue("dynamic_dependency");
      }
      if (node.type === "MemberExpression" && (name(node) === "currentScript" || (node.computed && literal(node.property) === null))) issue("dynamic_script_capability");
    });
  } catch {
    // 不能静态解析的脚本保留源码，不执行以探测依赖。
    issue("unsupported_script_syntax");
  }
  return { dependencies, issues };
}
