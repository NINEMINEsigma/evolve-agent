/**
 * 离线阅读器独立入口（独立 IIFE 构建）。
 *
 * 从文档中读取惰性 JSON 数据（EXPORT_DATA_ID script 标签），严格解码后挂载
 * OfflineViewer。不加载 App、Router、useWebSocket、Monaco 或运行时聊天 store。
 * 启动前完成格式/预算校验，失败显示可读失败文本，绝不连接 Gateway。
 */

import React from "react";
import ReactDOM from "react-dom/client";
import type { OfflineExportData } from "../types";
import { EXPORT_DATA_ID, EXPORT_LIMITS } from "../limits";
import { decodeExportSnapshot } from "../api";
import OfflineViewer from "./OfflineViewer";
import "../../../styles/variables.css";
import "../../../styles/base.css";
import "../../../styles/chat.css";
import "../../../styles/messages.css";
import "../../../styles/chat-style-scope.css";
import "../../../styles/agent-stage.css";
import "./viewer.css";

function renderFatal(root: HTMLElement, message: string): void {
  root.innerHTML = "";
  const container = document.createElement("div");
  container.className = "offline-fatal";
  container.textContent = message;
  root.appendChild(container);
}

function readExportData(): OfflineExportData {
  const node = document.getElementById(EXPORT_DATA_ID);
  if (!node || !node.textContent) throw new Error("Missing offline export data");
  if (new TextEncoder().encode(node.textContent).byteLength > EXPORT_LIMITS.archiveInputBytes) throw new Error("Offline document exceeds byte budget");
  const parsed: unknown = JSON.parse(node.textContent);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid offline export data");
  const raw = parsed as Record<string, unknown>;
  if (raw.formatVersion !== 1) throw new Error("Unsupported offline export format");
  if (!raw.snapshot || typeof raw.snapshot !== "object") throw new Error("Missing offline snapshot");
  // 复用正式严格解码校验 snapshot 结构（纯解码，不含网络执行）。
  const snapshot = decodeExportSnapshot(raw.snapshot);
  if (!Array.isArray(raw.assets)) throw new Error("Invalid offline assets");
  if (raw.assets.length > EXPORT_LIMITS.resources) throw new Error("Offline assets exceed budget");
  if (typeof raw.originalBaseUrl !== "string" || !raw.originalBaseUrl) throw new Error("Missing offline base url");
  if (typeof raw.stagePaused !== "boolean" || typeof raw.chatStylePaused !== "boolean") throw new Error("Invalid offline visual state");
  const ids = new Set<string>();
  let estimatedBytes = 0;
  for (const item of raw.assets) {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("Invalid offline asset");
    const asset = item as Record<string, unknown>;
    if (typeof asset.id !== "string" || !/^asset-\d+$/.test(asset.id) || ids.has(asset.id)
      || typeof asset.mime !== "string" || !/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/i.test(asset.mime)
      || typeof asset.base64 !== "string" || !/^[A-Za-z0-9+/]*={0,2}$/.test(asset.base64)
      || typeof asset.digest !== "string" || !/^[a-f0-9]{64}$/.test(asset.digest)) throw new Error("Invalid offline asset metadata");
    const bytes = Math.floor(asset.base64.length * 3 / 4) - (asset.base64.endsWith("==") ? 2 : asset.base64.endsWith("=") ? 1 : 0);
    if (asset.base64.length % 4 !== 0 || bytes > EXPORT_LIMITS.resourceBytes) throw new Error("Invalid offline asset size");
    estimatedBytes += bytes;
    if (estimatedBytes > EXPORT_LIMITS.resourceTotalBytes) throw new Error("Offline asset byte budget exceeded");
    ids.add(asset.id);
  }
  if (!raw.aliases || typeof raw.aliases !== "object" || Array.isArray(raw.aliases)) throw new Error("Invalid offline aliases");
  const aliases = raw.aliases as Record<string, string>;
  if (Object.keys(aliases).length > EXPORT_LIMITS.resources * EXPORT_LIMITS.depth) throw new Error("Offline alias budget exceeded");
  for (const id of Object.values(aliases)) if (typeof id !== "string" || !ids.has(id)) throw new Error("Unknown offline alias target");
  if (!raw.visualEntries || typeof raw.visualEntries !== "object" || Array.isArray(raw.visualEntries)) throw new Error("Invalid offline visuals");
  const visualEntries = raw.visualEntries as OfflineExportData["visualEntries"];
  if (Object.entries(visualEntries).some(([key, value]) => !["stage", "chat_style"].includes(key) || typeof value !== "string")) throw new Error("Invalid offline visual reference");
  if (!Array.isArray(raw.issues) || raw.issues.length > EXPORT_LIMITS.resources * EXPORT_LIMITS.depth) throw new Error("Invalid offline issue list");
  const issues = raw.issues;
  for (const item of issues) {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("Invalid offline issue");
    const issue = item as Record<string, unknown>;
    if (typeof issue.owner !== "string" || typeof issue.source !== "string" || typeof issue.code !== "string" || (issue.detail !== undefined && typeof issue.detail !== "string")) throw new Error("Invalid offline issue fields");
  }
  return {
    formatVersion: 1,
    snapshot,
    assets: raw.assets as OfflineExportData["assets"],
    aliases,
    issues: issues as OfflineExportData["issues"],
    visualEntries,
    originalBaseUrl: raw.originalBaseUrl,
    stagePaused: raw.stagePaused,
    chatStylePaused: raw.chatStylePaused,
  };
}

export function mountOfflineViewer(data: OfflineExportData, root: HTMLElement): void {
  try {
    ReactDOM.createRoot(root).render(
      <React.StrictMode>
        <OfflineViewer data={data} />
      </React.StrictMode>
    );
  } catch (error) {
    renderFatal(root, error instanceof Error ? error.message : "Offline viewer failed to start");
  }
}

const rootElement = document.getElementById("root");
if (rootElement) {
  try { mountOfflineViewer(readExportData(), rootElement); }
  catch (error) { renderFatal(rootElement, error instanceof Error ? error.message : "Offline export data is invalid"); }
}