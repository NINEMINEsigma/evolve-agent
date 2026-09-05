import { useEffect, useRef, useState, type ChangeEvent, type RefObject } from "react";
import RichInput from "./RichInput";
import TaskProgressPanel from "./TaskProgressPanel";
import InputMorph, { MorphItem } from "./InputMorph";
import RecorderButton from "./RecorderButton";
import TokenRing from "./TokenRing";
import PopupLayer from "./primitives/PopupLayer";
import type { PendingImage, PendingAudio, PendingVideo } from "../hooks/useWebSocket";
import type { AskRequest, ConfirmRequest, SubagentSession, TargetSessionOption, TaskProgress } from "../types";
import { escapeHtml } from "../utils";
import { SID_DISPLAY_LEN } from "../constants/session";
import { DIMENSIONS } from "../constants/dimensions";

// ── 左下功能组按钮间距（CSS .input-bar-actions-left gap 定值） ──
const ACTIONS_GAP = 6;
// 展开态固有宽度：7 按钮 × 单钮宽 + 6 间距（静态计算，防收起后振荡）
const EXPANDED_ACTIONS_WIDTH =
  7 * DIMENSIONS.INPUT_ACTION_BTN_WIDTH + 6 * ACTIONS_GAP;

// ── 模块级 SVG 图标常量：展开态按钮与菜单项复用同一引用 ──
const ICONS = {
  interrupt: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  ),
  disgust: <span className="disgust-emoji" role="img" aria-label="thumbs-down">👎</span>,
  upload: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  ),
  clipboard: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="8" y="3" width="8" height="4" rx="1" />
      <rect x="5" y="6" width="14" height="15" rx="2" />
    </svg>
  ),
  mic: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  ),
  agentspace: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
      <path d="M10 13l4-4M14 9h-4v4" />
    </svg>
  ),
  resume: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  ),
  menu: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  ),
};

interface InputBarProps {
  input: string;
  setInput: (v: string) => void;
  waiting: boolean;
  uploading: boolean;
  archived: boolean;
  hasActiveProfile: boolean;
  sessionId: string;
  /** 空态（无对话）时隐藏进度条 */
  chatEmpty: boolean;
  taskProgress: Record<string, TaskProgress>;
  onSend: () => void;
  onUpload: (e: ChangeEvent<HTMLInputElement>) => void;
  onUploadClick: () => Promise<void>;
  onInterrupt: () => void;
  onDisgust: () => void;
  onResume: () => void;
  fileInputRef: RefObject<HTMLInputElement>;
  pendingImages: PendingImage[];
  onRemovePendingImage: (id: string) => void;
  onPasteImage: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  pendingAudios: PendingAudio[];
  onRemovePendingAudio: (id: string) => void;
  onPasteAudio: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  pendingVideos: PendingVideo[];
  onRemovePendingVideo: (id: string) => void;
  onPasteVideo: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  inputRef: RefObject<HTMLDivElement>;
  subagentSessions: Record<string, SubagentSession>;
  targetSessions: string[];
  setTargetSessions: (ids: string[]) => void;
  // multi-agent visibility
  agents: string[];
  visibleCharacters: string[];
  responseCharacters: string[];
  onToggleAgentState: (agentName: string) => void;
  // 工具交互队列（ask/confirm 变形）
  pendingAsks: AskRequest[];
  pendingConfirms: ConfirmRequest[];
  onRespondAsk: (ask: AskRequest, option?: string, customText?: string) => void;
  onRespondConfirm: (confirm: ConfirmRequest, action: string, reason?: string) => void;
  // 上下文徽章数据
  tokenUsage: number;
  contextTokens: number;
  llmMaxContextTokens: number;
}

// ── 零测量静态判定 hook：按展开态固有宽度（常量）与视口比较，防收起后振荡 ──
function useActionsCollapsed() {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    const check = () => {
      setCollapsed(
        EXPANDED_ACTIONS_WIDTH > window.innerWidth * DIMENSIONS.INPUT_ACTIONS_COLLAPSE_RATIO,
      );
    };
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return collapsed;
}

export default function InputBar({
  input,
  setInput,
  uploading,
  archived,
  hasActiveProfile,
  sessionId,
  chatEmpty,
  taskProgress,
  onSend,
  onUpload,
  onUploadClick,
  onInterrupt,
  onDisgust,
  onResume,
  fileInputRef,
  pendingImages,
  onRemovePendingImage,
  onPasteImage,
  pendingAudios,
  onRemovePendingAudio,
  onPasteAudio,
  pendingVideos,
  onRemovePendingVideo,
  onPasteVideo,
  inputRef,
  subagentSessions,
  targetSessions,
  setTargetSessions,
  agents,
  visibleCharacters,
  responseCharacters,
  onToggleAgentState,
  pendingAsks,
  pendingConfirms,
  onRespondAsk,
  onRespondConfirm,
  tokenUsage,
  contextTokens,
  llmMaxContextTokens,
}: InputBarProps) {
  // ── 变形计算：confirm 队首优先于 ask ──
  const morphItem: MorphItem | null = pendingConfirms.length > 0
    ? { kind: "confirm", confirm: pendingConfirms[0] }
    : pendingAsks.length > 0
      ? { kind: "ask", ask: pendingAsks[0] }
      : null;
  const morphActive = morphItem !== null;
  const queueExtra = pendingConfirms.length + pendingAsks.length - (morphItem ? 1 : 0);

  // RichInput 的纯文本镜像（html 进 input state，text 供变形提交判断/取值）
  const [inputText, setInputText] = useState("");

  // 草稿暂存：进入变形时清空输入框供回答/理由使用，退出变形（队列排空）时还原；
  // 会话切换时丢弃暂存，防止旧会话草稿还原进新会话
  const draftRef = useRef<{ html: string; text: string } | null>(null);
  const prevSessionRef = useRef(sessionId);
  useEffect(() => {
    if (prevSessionRef.current !== sessionId) {
      prevSessionRef.current = sessionId;
      draftRef.current = null;
      return;
    }
    if (morphActive) {
      if (draftRef.current === null) {
        draftRef.current = { html: input, text: inputText };
        if (input) setInput("");
        if (inputText) setInputText("");
      }
    } else if (draftRef.current !== null) {
      setInput(draftRef.current.html);
      setInputText(draftRef.current.text);
      draftRef.current = null;
    }
  }, [morphActive, sessionId, input, inputText, setInput]);

  // ── 功能组收起判定 ──
  const collapsed = useActionsCollapsed();

  // ── 菜单状态 ──
  const [actionsMenu, setActionsMenu] = useState<{ x: number; y: number } | null>(null);
  const menuBtnRef = useRef<HTMLButtonElement>(null);

  if (archived) return null;

  const handlePasteClipboard = async () => {
    if (morphActive) return;
    if (!navigator?.clipboard?.readText) return;
    try {
      const text = await navigator.clipboard.readText();
      if (!text) return;
      const escaped = escapeHtml(text);
      const separator = input && !/\s$/.test(input) ? "\n" : "";
      setInput(input + separator + escaped);
    } catch {
      // 忽略剪贴板权限或读取失败
    }
  };

  const activeSubagents = Object.values(subagentSessions).filter(
    (s) => (s.status === "running" || s.status === "waiting") && s.interactive !== false
  );
  const hasSubagents = activeSubagents.length > 0;

  const targetOptions: TargetSessionOption[] = [
    { id: "main", name: "主会话" },
    ...activeSubagents
      .sort((a, b) => a.session_id.localeCompare(b.session_id))
      .map<TargetSessionOption>((s) => ({ id: s.session_id, name: s.name || s.session_id.slice(0, SID_DISPLAY_LEN), status: s.status })),
  ];

  const toggleTarget = (id: string) => {
    const selected = new Set(targetSessions);
    if (selected.has(id)) {
      selected.delete(id);
      if (selected.size === 0) {
        selected.add("main");
      }
    } else {
      selected.add(id);
    }
    setTargetSessions(Array.from(selected));
  };

  // ── 菜单按钮 toggle：拦截冒泡避免 PopupLayer outside-mousedown 先关闭，再切菜单 ──
  const handleMenuToggle = () => {
    setActionsMenu((prev) => {
      if (prev) return null;
      const rect = menuBtnRef.current?.getBoundingClientRect();
      return rect ? { x: rect.left, y: rect.top - 8 } : null;
    });
  };

  // ── 菜单项数据 ──
  const actionItems = [
    { key: "interrupt", label: "中断当前 Agent 工作", icon: ICONS.interrupt, disabled: false, action: onInterrupt },
    { key: "disgust", label: "表达强烈不满", icon: ICONS.disgust, disabled: false, action: onDisgust },
    { key: "upload", label: "添加附件", icon: ICONS.upload, disabled: uploading || morphActive, action: onUploadClick },
    { key: "clipboard", label: "粘贴系统剪贴板", icon: ICONS.clipboard, disabled: morphActive, action: handlePasteClipboard },
    { key: "mic", label: "点击开始录音", icon: ICONS.mic, disabled: morphActive || uploading, action: undefined },
    { key: "agentspace", label: "打开 Agentspace 编辑器", icon: ICONS.agentspace, disabled: false, action: () => window.open("/agentspace", "_blank") },
    { key: "resume", label: "恢复工具链执行", icon: ICONS.resume, disabled: morphActive, action: onResume },
  ];

  return (
    <footer className="input-bar">
      {!chatEmpty && (
        <TaskProgressPanel
          taskProgress={taskProgress}
        />
      )}
      
      <div className="input-bar-inner">
        {morphItem && (
          <InputMorph
            item={morphItem}
            queueExtra={queueExtra}
            inputText={inputText}
            onRespondAsk={onRespondAsk}
            onRespondConfirm={onRespondConfirm}
            onClearInput={() => {
              setInput("");
              setInputText("");
            }}
          />
        )}
        {hasSubagents && (
          <div className="input-target-row">
            {targetOptions.map((opt: TargetSessionOption) => {
              const active = targetSessions.includes(opt.id);
              const tooltip = `${opt.name} · 当前消息${active ? "将会" : "不会"}发送至该会话`;
              return (
              <button
                key={opt.id}
                type="button"
                className={`input-target-chip ${active ? "active" : ""} input-target-chip-${opt.status || "main"}`}
                onClick={() => toggleTarget(opt.id)}
                data-tooltip={tooltip}
                title={opt.name}
              >
                <span className="input-target-chip-dot" />
                {opt.name}
              </button>
              );
            })}
          </div>
        )}
        {agents.length > 0 && (
          <div className="input-agent-row">
            {agents.map((agent) => {
              const isVisible = visibleCharacters.includes(agent) || visibleCharacters.includes("all-agents");
              const isResponse = responseCharacters.includes(agent);
              const stateLabel = isResponse ? "需响应" : isVisible ? "仅可见" : "不可见";
              const stateClass = isResponse ? "state-response" : isVisible ? "state-visible" : "state-none";
              return (
                <button
                  key={agent}
                  type="button"
                  className={`input-agent-chip ${stateClass}`}
                  onClick={() => onToggleAgentState(agent)}
                  data-tooltip={`${agent} · ${stateLabel}`}
                >
                  <span className="input-agent-chip-dot" />
                  {agent}
                </button>
              );
            })}
          </div>
        )}
        
        {/* ── 上行：输入区独占整行 ── */}
        <RichInput
          ref={inputRef}
          value={input}
          onChange={(html, text) => {
            setInput(html);
            setInputText(text);
          }}
          onSend={morphActive ? () => {} : onSend}
          onPasteImage={onPasteImage}
          onRemoveImage={onRemovePendingImage}
          pendingImages={pendingImages}
          onPasteAudio={onPasteAudio}
          onRemoveAudio={onRemovePendingAudio}
          pendingAudios={pendingAudios}
          onPasteVideo={onPasteVideo}
          onRemoveVideo={onRemovePendingVideo}
          pendingVideos={pendingVideos}
          disabled={!hasActiveProfile}
          placeholder={
            morphItem
              ? morphItem.kind === "ask"
                ? "输入回答..."
                : "输入拒绝理由（可选）..."
              : hasActiveProfile
                ? "Send message to agent..."
                : "请先在模型配置中新建/选择一个配置"
          }
        />
        <input
          ref={fileInputRef}
          type="file"
          className="file-input-hidden"
          onChange={onUpload}
          multiple
          disabled={uploading}
        />
        
        {/* ── 下行：左组功能按键 + 右组上下文徽章 | 发送 ── */}
        <div className="input-bar-actions">
          <div className="input-bar-actions-left">
            {collapsed ? (
              <button
                ref={menuBtnRef}
                className="input-tool-btn"
                data-tooltip="功能菜单"
                type="button"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={handleMenuToggle}
              >
                {ICONS.menu}
              </button>
            ) : (
              <>
                <button
                  className="interrupt-btn"
                  onClick={onInterrupt}
                  data-tooltip="中断当前 Agent 工作"
                  type="button"
                >
                  {ICONS.interrupt}
                </button>
                <button
                  className="disgust-btn"
                  onClick={onDisgust}
                  data-tooltip="表达强烈不满（工具调用将被拒绝）"
                  type="button"
                >
                  {ICONS.disgust}
                </button>
                <button
                  className="input-tool-btn"
                  data-tooltip="添加附件"
                  type="button"
                  onClick={onUploadClick}
                  disabled={uploading || morphActive}
                >
                  {ICONS.upload}
                </button>
                <button
                  className="input-tool-btn"
                  data-tooltip="粘贴系统剪贴板"
                  type="button"
                  onClick={handlePasteClipboard}
                  disabled={morphActive}
                >
                  {ICONS.clipboard}
                </button>
                <RecorderButton
                  onRecordingComplete={(file) => onPasteAudio(file)}
                  disabled={morphActive || uploading}
                />
                <button
                  className="agentspace-fab"
                  data-tooltip="打开 Agentspace 编辑器"
                  type="button"
                  onClick={() => window.open("/agentspace", "_blank")}
                >
                  {ICONS.agentspace}
                </button>
                <button
                  className="resume-btn"
                  onClick={onResume}
                  data-tooltip="恢复工具链执行"
                  type="button"
                  disabled={morphActive}
                >
                  {ICONS.resume}
                </button>
              </>
            )}
          </div>
          
          <div className="input-bar-actions-right">
            <TokenRing
              contextTokens={contextTokens}
              llmMaxContextTokens={llmMaxContextTokens}
              tokenUsage={tokenUsage}
            />
            <button className="send-btn" onClick={onSend} disabled={morphActive || !hasActiveProfile} type="button">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
      
      {/* ── 功能组收起菜单（PopupLayer 承载，向上弹出） ── */}
      {actionsMenu && (
        <PopupLayer
          position={actionsMenu}
          className="input-actions-menu"
          style={{ transform: "translateY(-100%)" }}
          onClose={() => setActionsMenu(null)}
        >
          {actionItems.map((item) => {
            // 录音项特殊处理：包 RecorderButton 本体（内部已含 button，不可再嵌 button）
            if (item.key === "mic") {
              return (
                <div
                  key={item.key}
                  className="input-action-menu-item"
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <RecorderButton
                    onRecordingComplete={(file) => onPasteAudio(file)}
                    disabled={item.disabled}
                  />
                  <span>{item.label}</span>
                </div>
              );
            }
            return (
              <button
                key={item.key}
                className="input-action-menu-item"
                type="button"
                disabled={item.disabled}
                onClick={() => {
                  if (item.action) item.action();
                  setActionsMenu(null);
                }}
              >
                <span className="input-action-menu-icon">{item.icon}</span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </PopupLayer>
      )}
    </footer>
  );
}