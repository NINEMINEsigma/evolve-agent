export type SessionVariableKind = "number" | "string" | "invalid";
export type SessionVariableDisplay = "auto" | "number" | "bar" | "gauge";

export interface SessionVariableMetadataDto {
  label: string;
  description: string;
  min: number | null;
  max: number | null;
  integer: boolean;
  percent: boolean;
  display: SessionVariableDisplay;
}

export interface SessionVariableIssueDto {
  path: string;
  kind: "value" | "metadata" | "constraint" | "path";
  code: string;
  message: string;
  key: string | null;
}

export interface SessionVariableEntryDto {
  id: string;
  path: string;
  metadata_path: string;
  group: string;
  kind: SessionVariableKind;
  value: number | string | null;
  raw_value: string | null;
  raw_metadata: Record<string, string> | null;
  metadata: SessionVariableMetadataDto;
  issues: SessionVariableIssueDto[];
}

export interface SessionVariablePoolResponseDto {
  session_id: string;
  directory_path: string;
  root_exists: boolean;
  scan_complete: boolean;
  version: string;
  variables: SessionVariableEntryDto[];
  issues: SessionVariableIssueDto[];
}

export interface VariableGroup {
  path: string;
  name: string;
  entries: SessionVariableEntryDto[];
  children: VariableGroup[];
}
