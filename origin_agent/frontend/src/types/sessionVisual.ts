export type SessionVisualKind = "stage" | "site" | "chat_style";

/** 服务端资源快照；ready 不表示浏览器已渲染成功。 */
export interface SessionVisualServerState {
  readonly kind: SessionVisualKind;
  readonly status: "ready" | "missing";
  readonly source_path: string;
  readonly effective_path: string;
  readonly redirected: boolean;
  readonly redirect_error: string | null;
  readonly entry_name: string;
  readonly entry_url: string | null;
  readonly version: string | null;
}

export type SessionVisualResources = Readonly<Record<SessionVisualKind, SessionVisualServerState>>;

export type SessionVisualProbeMode = "entry" | "1";
export type SessionVisualUpdateStatus = "idle" | "checking" | "ready" | "error";

export type SessionVisualProbeResult =
  | { readonly status: "ready"; readonly finalUrl: string; readonly version: string }
  | { readonly status: "missing"; readonly error: string }
  | { readonly status: "forbidden"; readonly error: string }
  | { readonly status: "conflict"; readonly error: string };

/** 浏览器加载状态，与服务端资源快照分开。 */
export interface SessionVisualResourceState {
  readonly status: "idle" | "missing" | "ready" | "error";
  readonly finalUrl: string | null;
  readonly version: string | null;
  readonly reloadKey: number;
  readonly error: string | null;
  readonly updateStatus: SessionVisualUpdateStatus;
  readonly updateError: string | null;
  readonly refresh: () => void;
}
