export interface AgentLoopSettingsState {
  max_tool_turns: number | null;
  effective_max_tool_turns: number;
  default_max_tool_turns: number;
}

export type AgentLoopSettingsReadStatus = "idle" | "loading" | "ready" | "error";
export type AgentLoopSettingsSaveOutcome = "idle" | "saving" | "uncertain";

export interface AgentLoopSettingsRefreshOptions {
  discardDraft?: boolean;
}

export interface UseAgentLoopSettingsState {
  state: AgentLoopSettingsState | null;
  draft: string;
  readStatus: AgentLoopSettingsReadStatus;
  saveOutcome: AgentLoopSettingsSaveOutcome;
  loading: boolean;
  busy: boolean;
  dirty: boolean;
  error: string | null;
  notice: string | null;
  validationError: string | null;
  externalChange: boolean;
  shouldBlockUnload: boolean;
  setDraft: (value: string) => void;
  refresh: (options?: AgentLoopSettingsRefreshOptions) => Promise<boolean>;
  save: () => Promise<boolean>;
  restoreDefault: () => Promise<boolean>;
}
