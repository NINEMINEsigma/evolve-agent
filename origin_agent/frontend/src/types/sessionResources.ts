/**
 * Session-scoped resource snapshots shared by the WebSocket poller and the
 * read-only tab preview. Ownership and generation live on the resource Scope,
 * so a delayed response never commits into a newer session.
 */
import type {
  ClipboardDisplay,
  CronTask,
  DynamicEndpoint,
  ShellInfo,
  TaskProgress,
} from "../types";

/** 会话资源归属：sid 与单调递增代际（同 sid 重入也区分旧响应）。 */
export interface SessionResourceScope {
  sessionId: string;
  generation: number;
}

/** 一次在途读取的身份令牌；signal 用于主动取消。 */
export interface SessionResourceRequestToken extends SessionResourceScope {
  sequence: number;
  signal: AbortSignal;
}

/** 单一数据源的快照：data 为 null 表示尚未成功取得（未知），[] 才是已知空。 */
export interface SessionResourceSnapshot<T> extends SessionResourceScope {
  data: T | null;
  loading: boolean;
  error: string | null;
  updatedAt: number | null;
}

/** 泛型快照控制器：唯一读写入口，禁止另存第二份业务数组。 */
export interface SessionResourceState<T> {
  snapshot: SessionResourceSnapshot<T>;
  beginRequest: () => SessionResourceRequestToken | null;
  completeRequest: (token: SessionResourceRequestToken, data: T) => void;
  failRequest: (token: SessionResourceRequestToken, error: string) => void;
  setData: React.Dispatch<React.SetStateAction<T>>;
  reset: () => void;
}

export interface SessionResourceSnapshots {
  shells: SessionResourceSnapshot<ShellInfo[]>;
  cronTasks: SessionResourceSnapshot<CronTask[]>;
  dynamicEndpoints: SessionResourceSnapshot<DynamicEndpoint[]>;
}

/** 工具资源 GET 响应的稳定结构（仅取本任务消费必需字段）。 */
export interface SessionToolResourcesDto {
  session_id: string;
  task_progress: Record<string, TaskProgress>;
  clipboard_display: Record<string, ClipboardDisplay>;
  dynamic_endpoints: DynamicEndpoint[];
}