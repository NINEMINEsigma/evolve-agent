import type { HistoryContentRowDto } from "../chat/types";

export interface SessionExportStamp {
  loop_instance_id: string;
  export_epoch: number;
  history_digest: string;
  metadata_digest: string;
  visual_digest: string;
}
export interface ExportLimits {
  max_history_bytes: number;
  max_snapshot_bytes: number;
  max_messages: number;
  max_rows: number;
  max_nodes: number;
  max_structure_depth: number;
  max_resource_bytes: number;
  max_resource_total_bytes: number;
  max_resources: number;
  max_depth: number;
  max_verify_body_bytes: number;
  max_archive_input_bytes: number;
  request_timeout_seconds: number;
  total_timeout_seconds: number;
}
export interface ExportVisual {
  kind: "stage" | "chat_style";
  status: "ready" | "missing" | "error";
  configured: boolean;
  availability: "unconfigured" | "ready" | "missing_entry" | "invalid_metadata" | "unreadable";
  source_path: string;
  effective_path: string;
  entry_path: string | null;
  error_code: string | null;
}
export interface SessionExportSnapshotDto {
  format_version: 1;
  session_id: string;
  captured_at: string;
  title: string;
  tags: string[];
  history_count: number;
  rows: HistoryContentRowDto[];
  stamp: SessionExportStamp;
  visuals: ExportVisual[];
  limits: ExportLimits;
}
export interface ExportResourceSource {
  kind: "sandbox" | "local_font";
  path: string;
}
export interface ExportResourceProof {
  source: ExportResourceSource;
  status: "saved" | "missing" | "denied" | "too_large";
  digest: string | null;
  size: number | null;
  identity: string | null;
}
export interface ExportVerifyRequest {
  stamp: SessionExportStamp;
  resources: ExportResourceProof[];
}
export type ExportResourceReadResult =
  | { status: "saved"; bytes: Uint8Array; mime: string; proof: ExportResourceProof }
  | { status: "unavailable"; code: string; proof: ExportResourceProof | null };
export interface ExportIssue {
  owner: string;
  source: string;
  code: string;
  detail?: string;
}
export type ExportDocumentKind = "html" | "css" | "script" | "json" | "media";
export interface ExportDependency {
  url: string;
  baseUrl: string;
  kind: ExportDocumentKind;
  owner: string;
  depth: number;
}
export interface ExportAsset {
  id: string;
  sourceKey: string;
  mime: string;
  bytes: Uint8Array;
  digest: string;
}
export interface OfflineAsset {
  id: string;
  mime: string;
  base64: string;
  digest: string;
}
export interface ExportCollection {
  assets: ExportAsset[];
  aliases: Record<string, string>;
  proofs: ExportResourceProof[];
  issues: ExportIssue[];
  visualEntries: Partial<Record<ExportVisual["kind"], string>>;
}
export interface OfflineExportData {
  formatVersion: 1;
  snapshot: SessionExportSnapshotDto;
  assets: OfflineAsset[];
  aliases: Record<string, string>;
  issues: ExportIssue[];
  visualEntries: Partial<Record<ExportVisual["kind"], string>>;
  originalBaseUrl: string;
  stagePaused: boolean;
  chatStylePaused: boolean;
}
export interface ExportProgress { completed: number; total: number; bytes: number; issues: number }
export interface ExportResourceClient {
  read(source: ExportResourceSource, signal: AbortSignal): Promise<ExportResourceReadResult>;
}
export interface ExportCollectOptions {
  signal: AbortSignal;
  baseUrl: string;
  onProgress(progress: ExportProgress): void;
}
export interface ExportDependencyScan { dependencies: ExportDependency[]; issues: ExportIssue[] }
