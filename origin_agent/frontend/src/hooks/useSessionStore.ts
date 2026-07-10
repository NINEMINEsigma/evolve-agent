import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatMessage,
  ConfirmRequest,
  AskRequest,
  DownloadInfo,
  PlaylistEntry,
  TaskProgress,
  ClipboardDisplay,
  CronTask,
  SessionInfo,
  WSMessage,
  MessageContent,
} from "../types";
import { parseToolResult, generateUUID, extractMessageResources } from "../utils";

export interface SessionStoreCallbacks {
  onSessionHistory?: (sid: string) => void;
  onSessionRotated?: (newSid: string, oldSid: string) => void;
}

export type AddMessageFn = (
  role: ChatMessage["role"],
  content: MessageContent,
  imageMarkdown?: string,
  downloadInfo?: DownloadInfo,
  audioUrl?: string,
  audioAutoplay?: boolean,
  playlist?: PlaylistEntry[],
  playlistAutoplay?: boolean,
  messageIndex?: number
) => void;

export interface SessionStore {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  input: string;
  setInput: React.Dispatch<React.SetStateAction<string>>;
  waiting: boolean;
  setWaiting: React.Dispatch<React.SetStateAction<boolean>>;
  pendingConfirm: ConfirmRequest | null;
  setPendingConfirm: React.Dispatch<React.SetStateAction<ConfirmRequest | null>>;
  denyReason: string;
  setDenyReason: React.Dispatch<React.SetStateAction<string>>;
  pendingAsk: AskRequest | null;
  setPendingAsk: React.Dispatch<React.SetStateAction<AskRequest | null>>;
  askCustomText: string;
  setAskCustomText: React.Dispatch<React.SetStateAction<string>>;
  askSelectedOption: string | null;
  setAskSelectedOption: React.Dispatch<React.SetStateAction<string | null>>;
  sessionId: string;
  setSessionId: React.Dispatch<React.SetStateAction<string>>;
  tokenUsage: number;
  setTokenUsage: React.Dispatch<React.SetStateAction<number>>;
  contextTokens: number;
  setContextTokens: React.Dispatch<React.SetStateAction<number>>;
  sessions: SessionInfo[];
  setSessions: React.Dispatch<React.SetStateAction<SessionInfo[]>>;
  searchQuery: string;
  setSearchQuery: React.Dispatch<React.SetStateAction<string>>;
  handsfreeMode: boolean;
  setHandsfreeMode: React.Dispatch<React.SetStateAction<boolean>>;
  taskProgress: Record<string, TaskProgress>;
  setTaskProgress: React.Dispatch<React.SetStateAction<Record<string, TaskProgress>>>;
  clipboardDisplays: Record<string, ClipboardDisplay>;
  setClipboardDisplays: React.Dispatch<React.SetStateAction<Record<string, ClipboardDisplay>>>;
  agents: string[];
  setAgents: React.Dispatch<React.SetStateAction<string[]>>;
  llmMaxContextTokens: number;
  setLlmMaxContextTokens: React.Dispatch<React.SetStateAction<number>>;
  llmModelName: string;
  setLlmModelName: React.Dispatch<React.SetStateAction<string>>;
  approvalModelName: string;
  setApprovalModelName: React.Dispatch<React.SetStateAction<string>>;
  approvalModelAvailable: boolean;
  setApprovalModelAvailable: React.Dispatch<React.SetStateAction<boolean>>;
  mergeMode: boolean;
  setMergeMode: React.Dispatch<React.SetStateAction<boolean>>;
  selectedForMerge: Set<string>;
  setSelectedForMerge: React.Dispatch<React.SetStateAction<Set<string>>>;
  bgTasks: Array<{
    task_id: string;
    pid: number;
    command: string[];
    start_time: number;
    log_path: string;
    status: string;
  }>;
  setBgTasks: React.Dispatch<
    React.SetStateAction<
      Array<{
        task_id: string;
        pid: number;
        command: string[];
        start_time: number;
        log_path: string;
        status: string;
      }>
    >
  >;
  cronTasks: CronTask[];
  setCronTasks: React.Dispatch<React.SetStateAction<CronTask[]>>;
  terminatingSessions: Set<string>;
  setTerminatingSessions: React.Dispatch<React.SetStateAction<Set<string>>>;
  generatingTitleSessions: Set<string>;
  setGeneratingTitleSessions: React.Dispatch<React.SetStateAction<Set<string>>>;
  generatingTagSessions: Set<string>;
  setGeneratingTagSessions: React.Dispatch<React.SetStateAction<Set<string>>>;
  streamingMessage: ChatMessage | null;
  setStreamingMessage: React.Dispatch<React.SetStateAction<ChatMessage | null>>;
  allTags: string[];
  setAllTags: React.Dispatch<React.SetStateAction<string[]>>;
  streamingMessageRef: React.MutableRefObject<ChatMessage | null>;
  ignoreStaleRef: React.MutableRefObject<boolean>;
  streamDoneRef: React.MutableRefObject<boolean>;
  addMessage: AddMessageFn;
  fetchSessions: () => void;
  fetchAllTags: () => void;
  handleMessage: (msg: WSMessage) => void;
  toggleMessageCollapse: (id: string) => void;
  editMessage: (id: string, content: string) => Promise<void>;
  deleteMessages: (count?: number) => Promise<void>;
  regenerateResponse: () => Promise<void>;
  updateMessageVisibility: (messageIndex: number, visibleCharacters: string[]) => Promise<void>;
  respondConfirm: (pendingConfirm: ConfirmRequest | null, action: string, denyReasonText?: string, deniedBy?: string) => void;
  respondAsk: (pendingAsk: AskRequest | null, option?: string, customText?: string) => void;
  newChat: () => void;
  switchSession: (sid: string) => void;
  deleteSession: (sid: string) => void;
  autoTitleSession: (sid: string) => void;
  autoTagSession: (sid: string) => void;
  terminateSession: (sid: string) => void;
  togglePinSession: (sid: string) => void;
  mergeSessions: (sources: string[]) => void;
  branchSession: (sid: string) => void;
  toggleMergeSelect: (sid: string) => void;
  updateSessionTags: (sid: string, tags: string[]) => Promise<string[]>;
  sidebarSessions: SessionInfo[];
  sessionResources: import("../utils").MessageResources;
}

export function useSessionStore(callbacks: SessionStoreCallbacks = {}): SessionStore {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [denyReason, setDenyReason] = useState("用户不同意工具调用");
  const [pendingAsk, setPendingAsk] = useState<AskRequest | null>(null);
  const [askCustomText, setAskCustomText] = useState("");
  const [askSelectedOption, setAskSelectedOption] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [tokenUsage, setTokenUsage] = useState(0);
  const [contextTokens, setContextTokens] = useState(0);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [handsfreeMode, setHandsfreeMode] = useState(false);
  const [taskProgress, setTaskProgress] = useState<Record<string, TaskProgress>>({});
  const [clipboardDisplays, setClipboardDisplays] = useState<Record<string, ClipboardDisplay>>({});
  const [agents, setAgents] = useState<string[]>([]);
  const [llmMaxContextTokens, setLlmMaxContextTokens] = useState(0);
  const [llmModelName, setLlmModelName] = useState("");
  const [approvalModelName, setApprovalModelName] = useState("");
  const [approvalModelAvailable, setApprovalModelAvailable] = useState(false);
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set());
  const [bgTasks, setBgTasks] = useState<Array<{
    task_id: string;
    pid: number;
    command: string[];
    start_time: number;
    log_path: string;
    status: string;
  }>>([]);
  const [cronTasks, setCronTasks] = useState<CronTask[]>([]);
  const [terminatingSessions, setTerminatingSessions] = useState<Set<string>>(new Set());
  const [generatingTitleSessions, setGeneratingTitleSessions] = useState<Set<string>>(new Set());
  const [generatingTagSessions, setGeneratingTagSessions] = useState<Set<string>>(new Set());
  const [streamingMessage, setStreamingMessage] = useState<ChatMessage | null>(null);
  const [allTags, setAllTags] = useState<string[]>([]);

  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const streamingMessageRef = useRef<ChatMessage | null>(null);
  useEffect(() => {
    streamingMessageRef.current = streamingMessage;
  }, [streamingMessage]);

  const ignoreStaleRef = useRef(false);
  const streamDoneRef = useRef(false);
  const reasoningStartRef = useRef<number | null>(null);
  const callbacksRef = useRef(callbacks);
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  const nextMessageIndex = useCallback((items: ChatMessage[]) => {
    const indexes = items
      .map((m) => m.messageIndex)
      .filter((index): index is number => typeof index === "number");
    return indexes.length ? Math.max(...indexes) + 1 : 0;
  }, []);

  const ensureStreamingMessage = useCallback((streamId: string, characterName?: string) => {
    setStreamingMessage((prev) => {
      if (prev && prev.id === streamId) return prev;
      reasoningStartRef.current = null;
      return {
        role: "assistant",
        content: "",
        id: streamId,
        characterName,
        reasoningContent: undefined,
        messageIndex: nextMessageIndex(messagesRef.current),
      };
    });
  }, [nextMessageIndex]);

  const flushStreamingMessage = useCallback(() => {
    setStreamingMessage((prev) => {
      if (!prev) return null;
      let finalPrev = prev;
      if (reasoningStartRef.current && prev.reasoningContent) {
        const duration = Math.round((Date.now() - reasoningStartRef.current) / 1000);
        finalPrev = { ...prev, reasoningDuration: duration };
        reasoningStartRef.current = null;
      }
      setMessages((m) => {
        const exists = m.some((x) => x.id === finalPrev.id);
        return exists ? m.map((x) => (x.id === finalPrev.id ? finalPrev : x)) : [...m, finalPrev];
      });
      return null;
    });
  }, []);

  const appendStreamingDelta = useCallback((
    streamId: string,
    delta: string,
    reasoningDelta?: string,
    toolCall?: unknown,
    characterName?: string
  ) => {
    ensureStreamingMessage(streamId, characterName);
    if (reasoningDelta && reasoningStartRef.current == null) {
      reasoningStartRef.current = Date.now();
    }
    setStreamingMessage((prev) => {
      if (!prev) return null;
      const content = typeof prev.content === "string" ? prev.content : "";
      const reasoning = prev.reasoningContent || "";
      let nextContent: string = content;
      let nextReasoning: string | undefined = reasoning || undefined;
      let nextToolName: string | undefined = prev.toolName;
      let nextToolArgs: Record<string, unknown> | undefined = prev.toolArgs;
      if (delta) nextContent = content + delta;
      if (reasoningDelta) nextReasoning = reasoning + reasoningDelta;
      if (toolCall && typeof toolCall === "object") {
        const tc = toolCall as Record<string, unknown>;
        if (typeof tc.name === "string") nextToolName = tc.name;
        if (typeof tc.arguments === "object" && tc.arguments !== null) {
          nextToolArgs = tc.arguments as Record<string, unknown>;
        }
      }
      return { ...prev, content: nextContent, reasoningContent: nextReasoning, toolName: nextToolName, toolArgs: nextToolArgs };
    });
  }, [ensureStreamingMessage]);

  const addMessage = useCallback((
    role: ChatMessage["role"],
    content: MessageContent,
    imageMarkdown?: string,
    downloadInfo?: DownloadInfo,
    audioUrl?: string,
    audioAutoplay?: boolean,
    playlist?: PlaylistEntry[],
    playlistAutoplay?: boolean,
    messageIndex?: number
  ) => {
    const id = generateUUID();
    setMessages((prev) => [...prev, {
      role, content, id, imageMarkdown, downloadInfo, audioUrl, audioAutoplay, playlist, playlistAutoplay, messageIndex
    }]);
  }, []);

  const fetchSessions = useCallback(() => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  const fetchAllTags = useCallback(() => {
    fetch("/api/tags")
      .then((r) => r.json())
      .then((data) => setAllTags(data.tags || []))
      .catch(() => {});
  }, []);

  const handleMessage = useCallback((msg: WSMessage) => {
    if (msg.type === "pong") return; // connection hook handles pong

    if (msg.type === "system") {
      const raw = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content ?? "");
      try {
        const data = JSON.parse(raw);
        if (data.build_hash) {
          const lastHash = localStorage.getItem("evolve_build_hash") || "";
          if (lastHash && lastHash !== data.build_hash) {
            localStorage.setItem("evolve_build_hash", data.build_hash);
            window.location.reload();
            return;
          }
          localStorage.setItem("evolve_build_hash", data.build_hash);
          return;
        }
        if (data.server_info) {
          const info = data.server_info;
          if (info.llm_max_context_tokens) setLlmMaxContextTokens(info.llm_max_context_tokens);
          setLlmModelName(info.llm_model || "");
          setApprovalModelName(info.approval_model_name || "");
          setApprovalModelAvailable(info.approval_model_available || false);
          return;
        }
        if (data.session_history) {
          const history = data.session_history.flatMap((m: any) => {
            if (m.role === "assistant" && Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
              return m.tool_calls.map((tc: any) => {
                const toolName = tc.function?.name || "tool";
                let toolArgs = tc.function?.arguments || {};
                if (typeof toolArgs === "string") {
                  try {
                    toolArgs = JSON.parse(toolArgs);
                  } catch {
                    toolArgs = {};
                  }
                }
                const argsStr = toolArgs && typeof toolArgs === "object"
                  ? "(" + Object.entries(toolArgs)
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(", ") + ")"
                  : "";
                const callerPrefix = m.character_name ? `${m.character_name} ` : "";
                return {
                  role: "tool",
                  content: `${callerPrefix}⚡ ${toolName} ${argsStr}`,
                  id: generateUUID(),
                  toolName,
                  toolArgs,
                  characterName: m.character_name,
                  messageIndex: typeof m.index === "number" ? m.index : undefined,
                };
              });
            }
            const entry: any = {
              role: m.role,
              content: m.content,
              id: generateUUID(),
              messageIndex: typeof m.index === "number" ? m.index : undefined,
            };
            if (m.character_name) entry.characterName = m.character_name;
            if (m.visible_characters) entry.visibleCharacters = m.visible_characters;
            if (m.response_characters && m.response_characters.length > 0) {
              entry.responseCharacters = m.response_characters;
            }
            if (typeof m.requires_response === "boolean") entry.requiresResponse = m.requires_response;
            if (m.message_suffix) entry.messageSuffix = m.message_suffix;
            if (m.dynamic_message_suffix) entry.dynamicMessageSuffix = m.dynamic_message_suffix;
            if (m.reasoning_content) entry.reasoningContent = m.reasoning_content;
            if (m.role === "tool" && typeof m.content === "string") {
              const parsed = parseToolResult(m.content);
              if (parsed.imageMarkdown) entry.imageMarkdown = parsed.imageMarkdown;
              if (parsed.downloadInfo) entry.downloadInfo = parsed.downloadInfo;
              if (parsed.audioUrl) {
                entry.audioUrl = parsed.audioUrl;
                entry.audioAutoplay = parsed.audioAutoplay;
              }
              if (parsed.playlist) {
                entry.playlist = parsed.playlist;
                entry.playlistAutoplay = parsed.playlistAutoplay;
              }
              if (parsed.content !== undefined) entry.content = parsed.content;
            }
            return entry;
          });
          if (history.length) {
            setMessages(history);
          }
          if (data.agents && Array.isArray(data.agents)) {
            setAgents(data.agents);
          } else if ("agents" in data) {
            setAgents([]);
          }
          if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
          if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
          if (data.processing) setWaiting(true);
          if (msg.session_id) {
            setSessionId(msg.session_id);
            localStorage.setItem("evolve_session_id", msg.session_id);
            callbacksRef.current.onSessionHistory?.(msg.session_id);
          }
          return;
        }
        if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
        if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
        if (data.token_usage !== undefined || data.context_tokens !== undefined) return;
        if (data.regenerate_trim) {
          const keepCount = data.keep_count as number;
          setMessages((prev) => prev.filter((m) =>
            typeof m.messageIndex === "number" && m.messageIndex < keepCount
          ));
          return;
        }
        if (data.action === "session_rotated") {
          const oldSid = sessionId;
          setSessionId(data.new_sid);
          localStorage.setItem("evolve_session_id", data.new_sid);
          setMessages([]);
          setTokenUsage(0);
          setClipboardDisplays({});
          setTaskProgress({});
          callbacksRef.current.onSessionRotated?.(data.new_sid, oldSid);
          callbacksRef.current.onSessionHistory?.(data.new_sid);
          fetchSessions();
          return;
        }
        if (data.uploaded) {
          addMessage("system", `✅ 上传成功：${data.filename || "文件"} → ${data.path}`);
          return;
        }
        if (data.agents && Array.isArray(data.agents)) {
          setAgents(data.agents);
          return;
        }
        if ("agents" in data) {
          setAgents([]);
          return;
        }
        if (data.stream_meta) {
          const meta = data.stream_meta as { stream_id: string; visible_characters?: string[]; response_characters?: string[] };
          setMessages((prev) => prev.map((m) =>
            m.id === meta.stream_id ? {
              ...m,
              visibleCharacters: meta.visible_characters,
              responseCharacters: meta.response_characters,
            } : m
          ));
          return;
        }
        if (data.assistant_text) {
          const p = JSON.parse(data.assistant_text);
          const id = generateUUID();
          setMessages((prev) => [...prev, {
            role: "assistant",
            content: p.content || "",
            id,
            reasoningContent: p.reasoning || undefined,
            messageIndex: nextMessageIndex(prev),
          }]);
          return;
        }
      } catch {}
      addMessage("system", raw);
      if (msg.session_id) {
        setSessionId(msg.session_id);
        localStorage.setItem("evolve_session_id", msg.session_id);
        callbacksRef.current.onSessionHistory?.(msg.session_id);
      }
      return;
    }

    if (msg.type === "user_message") {
      const incomingClientId = (msg as any).client_message_id as string | undefined;
      setMessages((prev) => {
        if (incomingClientId && prev.some((m) => m.clientMessageId === incomingClientId)) {
          return prev.map((m) =>
            m.clientMessageId === incomingClientId
              ? {
                  ...m,
                  content: msg.content ?? m.content,
                  characterName: msg.character_name ?? m.characterName,
                  messageIndex: typeof msg.index === "number" ? msg.index : m.messageIndex,
                  visibleCharacters: msg.visible_characters ?? m.visibleCharacters,
                  responseCharacters: msg.response_characters ?? m.responseCharacters,
                  messageSuffix: (msg as any).message_suffix ?? m.messageSuffix,
                  dynamicMessageSuffix: (msg as any).dynamic_message_suffix ?? m.dynamicMessageSuffix,
                }
              : m
          );
        }
        return [...prev, {
          role: "user",
          content: msg.content ?? "",
          id: generateUUID(),
          clientMessageId: incomingClientId,
          characterName: msg.character_name,
          messageIndex: typeof msg.index === "number" ? msg.index : undefined,
          visibleCharacters: msg.visible_characters ?? undefined,
          responseCharacters: msg.response_characters ?? undefined,
          messageSuffix: (msg as any).message_suffix ?? undefined,
          dynamicMessageSuffix: (msg as any).dynamic_message_suffix ?? undefined,
        }];
      });
      return;
    }

    if (msg.type === "assistant_message") {
      setWaiting(false);
      ignoreStaleRef.current = false;
      if (streamDoneRef.current) {
        streamDoneRef.current = false;
        fetchSessions();
        return;
      }
      if (msg.session_id && streamingMessageRef.current && streamingMessageRef.current.id === msg.stream_id) {
        flushStreamingMessage();
      } else {
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: msg.content ?? "",
          id: generateUUID(),
          characterName: msg.character_name,
          messageIndex: nextMessageIndex(prev),
          visibleCharacters: msg.visible_characters ?? undefined,
          responseCharacters: msg.response_characters ?? undefined,
          messageSuffix: (msg as any).message_suffix ?? undefined,
          dynamicMessageSuffix: (msg as any).dynamic_message_suffix ?? undefined,
        }]);
      }
      fetchSessions();
      return;
    }

    if (msg.type === "stream_delta") {
      if (ignoreStaleRef.current) return;
      const delta = msg.delta || "";
      const reasoningDelta = msg.reasoning_delta;
      let toolCall: unknown = undefined;
      if (typeof msg.content === "string") {
        try {
          const parsed = JSON.parse(msg.content);
          toolCall = parsed?.tool_call;
        } catch {}
      }
      appendStreamingDelta(msg.stream_id || "", delta, reasoningDelta, toolCall, msg.character_name);
      return;
    }

    if (msg.type === "stream_done") {
      setWaiting(false);
      ignoreStaleRef.current = false;
      flushStreamingMessage();
      streamDoneRef.current = true;
      return;
    }

    if (msg.type === "tool_call") {
      if (ignoreStaleRef.current) return;
      flushStreamingMessage();
      const argsStr = msg.args
        ? "(" + Object.entries(msg.args)
            .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
            .join(", ") + ")"
        : "";
      const callerPrefix = msg.character_name ? `${msg.character_name} ` : "";
      setMessages((prev) => [...prev, {
        role: "tool",
        content: `${callerPrefix}⚡ ${msg.tool} ${argsStr}`,
        id: generateUUID(),
        toolName: msg.tool,
        toolArgs: msg.args,
        characterName: msg.character_name,
        messageIndex: nextMessageIndex(prev),
      }]);
      return;
    }

    if (msg.type === "tool_result") {
      if (ignoreStaleRef.current) return;
      const raw = msg.result ?? "";
      const parsed = parseToolResult(raw, msg.tool);
      setMessages((prev) => [...prev, {
        role: "tool",
        content: parsed.content ?? `✅ ${msg.tool} → ${raw.slice(0, 2000)}`,
        id: generateUUID(),
        characterName: msg.character_name,
        imageMarkdown: parsed.imageMarkdown,
        downloadInfo: parsed.downloadInfo,
        audioUrl: parsed.audioUrl,
        audioAutoplay: parsed.audioAutoplay ?? false,
        playlist: parsed.playlist,
        playlistAutoplay: parsed.playlistAutoplay ?? false,
        messageIndex: nextMessageIndex(prev),
      }]);
      return;
    }

    if (msg.type === "task_progress") {
      const raw = msg.result ?? "";
      try {
        const data = JSON.parse(raw);
        if (data.cleared) {
          setTaskProgress((prev) => {
            const next = { ...prev };
            if (Array.isArray(data.cleared) && data.cleared.length) {
              for (const tid of data.cleared) delete next[tid];
            } else {
              return {};
            }
            return next;
          });
        } else if (data.task_id) {
          setTaskProgress((prev) => ({
            ...prev,
            [data.task_id]: {
              task_id: data.task_id,
              label: data.label || data.task_id,
              current: data.current ?? 0,
              total: data.total ?? 100,
              percent: data.percent ?? 0,
              status: data.status || "running",
            },
          }));
        }
      } catch {}
      return;
    }

    if (msg.type === "clipboard_display") {
      const raw = msg.result ?? "";
      try {
        const data = JSON.parse(raw);
        if (data.cleared) {
          setClipboardDisplays((prev) => {
            const next = { ...prev };
            if (Array.isArray(data.cleared) && data.cleared.length) {
              for (const did of data.cleared) delete next[did];
            } else {
              return {};
            }
            return next;
          });
        } else if (data.display_id) {
          setClipboardDisplays((prev) => ({
            ...prev,
            [data.display_id]: {
              display_id: data.display_id,
              label: data.label || data.display_id,
              content: data.content ?? "",
            },
          }));
        }
      } catch {}
      return;
    }

    if (msg.type === "error") {
      addMessage("error", msg.message ?? "");
      return;
    }

    if (msg.type === "confirm_request") {
      if (msg.request_id) {
        setDenyReason("用户不同意工具调用");
        setPendingConfirm({
          request_id: msg.request_id,
          content: typeof msg.content === "string" ? msg.content : "运行命令?",
          command: (msg.args as Record<string, unknown>)?.command as string[] | undefined,
          reason: (msg.args as Record<string, unknown>)?.reason as string | undefined,
          tool: msg.tool ?? undefined,
        });
      }
      return;
    }

    if (msg.type === "ask_request") {
      if (msg.request_id && msg.question) {
        setAskCustomText("");
        setAskSelectedOption(null);
        setPendingAsk({
          request_id: msg.request_id,
          question: msg.question ?? "",
          options: msg.options,
          allow_custom: msg.allow_custom ?? true,
        });
      }
    }
  }, [addMessage, appendStreamingDelta, fetchSessions, flushStreamingMessage, nextMessageIndex, sessionId]);

  const toggleMessageCollapse = useCallback((id: string) => {
    setMessages((prev) => prev.map((m) => (
      m.id === id ? { ...m, collapsed: m.collapsed === undefined ? false : !m.collapsed } : m
    )));
  }, []);

  const editMessage = useCallback(async (id: string, content: string) => {
    const target = messages.find((m) => m.id === id);
    if (!target || typeof target.messageIndex !== "number") {
      addMessage("error", "这条消息还没有可持久化的历史索引，无法编辑。");
      return;
    }
    const resp = await fetch(`/api/sessions/${sessionId}/messages/${target.messageIndex}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.updated) {
      addMessage("error", `消息编辑失败：${data.error || "unknown error"}`);
      return;
    }
    setMessages((prev) => prev.map((m) => (
      m.id === id ? { ...m, content: data.content ?? content, edited: true } : m
    )));
  }, [addMessage, messages, sessionId]);

  const deleteMessages = useCallback(async (count: number = 1) => {
    const resp = await fetch(`/api/sessions/${sessionId}/messages?count=${count}`, {
      method: "DELETE",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.deleted) {
      addMessage("error", `删除失败：${data.error || "unknown error"}`);
      return;
    }
    const remaining = data.remaining_count as number;
    setMessages((prev) => prev.filter((m) =>
      typeof m.messageIndex === "number" && m.messageIndex < remaining
    ));
  }, [sessionId, addMessage]);

  const regenerateResponse = useCallback(async () => {
    setWaiting(true);
    const resp = await fetch(`/api/sessions/${sessionId}/regenerate`, {
      method: "POST",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.regenerate) {
      setWaiting(false);
      addMessage("error", `重新生成失败：${data.error || "unknown error"}`);
    }
  }, [sessionId, addMessage]);

  const updateMessageVisibility = useCallback(async (messageIndex: number, visibleCharacters: string[]) => {
    try {
      const resp = await fetch(`/api/sessions/${sessionId}/messages/${messageIndex}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visible_characters: visibleCharacters }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.updated) {
        setMessages((prev) => prev.map((m) =>
          m.messageIndex === messageIndex ? { ...m, visibleCharacters: data.visible_characters ?? visibleCharacters } : m
        ));
      }
    } catch {}
  }, [sessionId]);

  const respondConfirm = useCallback((currentPending: ConfirmRequest | null, action: string, denyReasonText?: string, deniedBy?: string) => {
    if (!currentPending) return;
    const payload: Record<string, string> = { action };
    if (action === "deny" && denyReasonText) {
      payload.deny_reason = denyReasonText;
      payload.denied_by = deniedBy || "user";
    }
    fetch(`/api/confirm/${currentPending.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[confirm] fetch failed", err));
    setPendingConfirm(null);
  }, []);

  const respondAsk = useCallback((currentPending: AskRequest | null, option?: string, customText?: string) => {
    if (!currentPending) return;
    const payload: Record<string, string | null> = {
      option: option ?? null,
      custom_text: customText ?? null,
    };
    fetch(`/api/ask/${currentPending.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[ask] fetch failed", err));
    setPendingAsk(null);
    setAskCustomText("");
    setAskSelectedOption(null);
  }, []);

  const newChat = useCallback(() => {
    localStorage.removeItem("evolve_session_id");
    setMessages([]);
    setAgents([]);
    setInput("");
    setSessionId("");
    setWaiting(false);
    setPendingConfirm(null);
    setHandsfreeMode(false);
    setClipboardDisplays({});
    setTaskProgress({});
    ignoreStaleRef.current = false;
  }, []);

  const switchSession = useCallback((sid: string) => {
    if (sid === sessionId) return;
    localStorage.setItem("evolve_session_id", sid);
    setMessages([]);
    setAgents([]);
    setInput("");
    setSessionId(sid);
    setWaiting(false);
    setPendingConfirm(null);
    setClipboardDisplays({});
    setTaskProgress({});
    ignoreStaleRef.current = false;
  }, [sessionId]);

  const deleteSession = useCallback((sid: string) => {
    if (!confirm("确定要删除这个会话吗？此操作不可撤销。")) return;
    fetch(`/api/sessions/${sid}`, { method: "DELETE" })
      .then(() => {
        const remaining = sessions.filter((s) => s.id !== sid);
        setSessions(remaining);
      })
      .catch(() => {});
  }, [sessions, sessionId]);

  const autoTitleSession = useCallback((sid: string) => {
    setGeneratingTitleSessions((prev) => new Set(prev).add(sid));
    fetch(`/api/sessions/${sid}/auto-title`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.title) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title: data.title } : s)));
          fetchSessions();
        }
      })
      .catch(() => {})
      .finally(() => {
        setGeneratingTitleSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions]);

  const autoTagSession = useCallback((sid: string) => {
    setGeneratingTagSessions((prev) => new Set(prev).add(sid));
    fetch(`/api/sessions/${sid}/auto-tags`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.tags && Array.isArray(data.tags)) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, tags: data.tags } : s)));
          fetchSessions();
          fetchAllTags();
        }
      })
      .catch(() => {})
      .finally(() => {
        setGeneratingTagSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions, fetchAllTags]);

  const terminateSession = useCallback((sid: string) => {
    setTerminatingSessions((prev) => new Set(prev).add(sid));
    addMessage("system", "⏳ 正在终结会话，请稍候...");
    fetch(`/api/sessions/${sid}/terminate`, { method: "POST" })
      .then(() => {
        addMessage("system", "✅ 会话已终结");
        fetchSessions();
      })
      .catch(() => {
        addMessage("error", "❌ 终结会话失败");
      })
      .finally(() => {
        setTerminatingSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions, addMessage]);

  const togglePinSession = useCallback((sid: string) => {
    fetch(`/api/sessions/${sid}/pin`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, pinned: data.pinned } : s)));
        fetchSessions();
      })
      .catch(() => {});
  }, [fetchSessions]);

  const mergeSessions = useCallback((sources: string[]) => {
    const validSources = sources.filter((sid) => {
      const session = sessions.find((s) => s.id === sid);
      return session && session.status === "archived";
    });
    if (validSources.length < 1) {
      console.warn("[merge] 没有可合并的已归档会话");
      return;
    }
    if (validSources.length !== sources.length) {
      const skipped = sources.filter((sid) => !validSources.includes(sid));
      console.warn(`[merge] 以下未归档会话被排除: ${skipped.join(", ")}`);
    }
    fetch("/api/sessions/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources: validSources }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.session_id) {
          switchSession(data.session_id);
          fetchSessions();
        }
      })
      .catch(() => {});
  }, [switchSession, fetchSessions, sessions]);

  const branchSession = useCallback((sid: string) => mergeSessions([sid]), [mergeSessions]);

  const updateSessionTags = useCallback(async (sid: string, tags: string[]) => {
    const valid = tags
      .map((t) => t.trim())
      .filter((t) => {
        if (!t) return false;
        const zh = /^[\u4e00-\u9fa5]{1,5}$/.test(t);
        const en = /^[a-zA-Z]{1,10}$/.test(t);
        return zh || en;
      });
    const resp = await fetch(`/api/sessions/${sid}/tags`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: valid }),
    });
    const data = await resp.json().catch(() => ({}));
    if (data.updated) {
      setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, tags: data.tags || valid } : s)));
      fetchSessions();
    }
    return data.tags || valid;
  }, [fetchSessions]);

  const toggleMergeSelect = useCallback((sid: string) => {
    const session = sessions.find((s) => s.id === sid);
    if (!session || session.status !== "archived") {
      console.warn(`[merge] 会话 ${sid.slice(0, 8)} 未归档，不可合并`);
      return;
    }
    setSelectedForMerge((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });
  }, [sessions]);

  const sidebarSessions = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    const filtered = q
      ? sessions.filter((s) => {
          const text = (s.title || s.id).toLowerCase();
          if (text.includes(q)) return true;
          const tags = s.tags || [];
          return tags.some((t) => t.toLowerCase().includes(q));
        })
      : sessions;
    return filtered.sort((a, b) => {
      if (Number(b.pinned) !== Number(a.pinned)) return Number(b.pinned) - Number(a.pinned);
      return (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at);
    });
  }, [sessions, searchQuery]);

  const sessionResources = useMemo(() => extractMessageResources(messages), [messages]);

  return {
    messages,
    setMessages,
    input,
    setInput,
    waiting,
    setWaiting,
    pendingConfirm,
    setPendingConfirm,
    denyReason,
    setDenyReason,
    pendingAsk,
    setPendingAsk,
    askCustomText,
    setAskCustomText,
    askSelectedOption,
    setAskSelectedOption,
    sessionId,
    setSessionId,
    tokenUsage,
    setTokenUsage,
    contextTokens,
    setContextTokens,
    sessions,
    setSessions,
    searchQuery,
    setSearchQuery,
    handsfreeMode,
    setHandsfreeMode,
    taskProgress,
    setTaskProgress,
    clipboardDisplays,
    setClipboardDisplays,
    agents,
    setAgents,
    llmMaxContextTokens,
    setLlmMaxContextTokens,
    llmModelName,
    setLlmModelName,
    approvalModelName,
    setApprovalModelName,
    approvalModelAvailable,
    setApprovalModelAvailable,
    mergeMode,
    setMergeMode,
    selectedForMerge,
    setSelectedForMerge,
    bgTasks,
    setBgTasks,
    cronTasks,
    setCronTasks,
    terminatingSessions,
    setTerminatingSessions,
    generatingTitleSessions,
    setGeneratingTitleSessions,
    generatingTagSessions,
    setGeneratingTagSessions,
    streamingMessage,
    setStreamingMessage,
    streamingMessageRef,
    allTags,
    setAllTags,
    ignoreStaleRef,
    streamDoneRef,
    addMessage,
    fetchSessions,
    fetchAllTags,
    handleMessage,
    toggleMessageCollapse,
    editMessage,
    deleteMessages,
    regenerateResponse,
    updateMessageVisibility,
    respondConfirm,
    respondAsk,
    newChat,
    switchSession,
    deleteSession,
    autoTitleSession,
    autoTagSession,
    terminateSession,
    togglePinSession,
    mergeSessions,
    branchSession,
    toggleMergeSelect,
    updateSessionTags,
    sidebarSessions,
    sessionResources,
  };
}