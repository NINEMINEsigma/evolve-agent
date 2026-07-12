import type { ChangeEvent, RefObject } from "react";
import RichInput from "./RichInput";
import type { PendingImage } from "../hooks/useWebSocket";
import type { SubagentSession, TargetSessionOption } from "../types";
import { escapeHtml } from "../utils";

interface InputBarProps {
  input: string;
  setInput: (v: string) => void;
  waiting: boolean;
  uploading: boolean;
  archived: boolean;
  onSend: () => void;
  onUpload: (e: ChangeEvent<HTMLInputElement>) => void;
  onUploadClick: () => Promise<void>;
  onInterrupt: () => void;
  fileInputRef: RefObject<HTMLInputElement>;
  pendingImages: PendingImage[];
  onRemovePendingImage: (id: string) => void;
  onPasteImage: (file: File) => Promise<{ id: string; dataUrl: string } | null>;
  inputRef: RefObject<HTMLDivElement>;
  subagentSessions: Record<string, SubagentSession>;
  targetSessions: string[];
  setTargetSessions: (ids: string[]) => void;
  // multi-agent visibility
  agents: string[];
  visibleCharacters: string[];
  responseCharacters: string[];
  onToggleAgentState: (agentName: string) => void;
}

export default function InputBar({
  input,
  setInput,
  waiting,
  uploading,
  archived,
  onSend,
  onUpload,
  onUploadClick,
  onInterrupt,
  fileInputRef,
  pendingImages,
  onRemovePendingImage,
  onPasteImage,
  inputRef,
  subagentSessions,
  targetSessions,
  setTargetSessions,
  agents,
  visibleCharacters,
  responseCharacters,
  onToggleAgentState,
}: InputBarProps) {
  if (archived) return null;

  const handlePasteClipboard = async () => {
    if (waiting) return;
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
    (s) => s.status === "running" || s.status === "waiting"
  );
  const hasSubagents = activeSubagents.length > 0;

  const targetOptions: TargetSessionOption[] = [
    { id: "main", name: "主会话" },
    ...activeSubagents
      .sort((a, b) => a.session_id.localeCompare(b.session_id))
      .map((s) => ({ id: s.session_id, name: s.name || s.session_id.slice(0, 12), status: s.status })),
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

  return (
    <footer className="input-bar">
      <div className="input-bar-inner">
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
        <div className="input-bar-row">
          <button
            className="input-tool-btn"
            data-tooltip="添加附件"
            type="button"
            onClick={onUploadClick}
            disabled={uploading}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </button>
          <button
            className="input-tool-btn"
            data-tooltip="粘贴系统剪贴板"
            type="button"
            onClick={handlePasteClipboard}
            disabled={waiting}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="8" y="3" width="8" height="4" rx="1" />
              <rect x="5" y="6" width="14" height="15" rx="2" />
            </svg>
          </button>
          <RichInput
            ref={inputRef}
            value={input}
            onChange={(html) => setInput(html)}
            onSend={onSend}
            onPasteImage={onPasteImage}
            onRemoveImage={onRemovePendingImage}
            pendingImages={pendingImages}
            disabled={waiting}
            placeholder="Send message to agent..."
          />
          <input
            ref={fileInputRef}
            type="file"
            className="file-input-hidden"
            onChange={onUpload}
            multiple
            disabled={uploading}
          />
          <button className="send-btn" onClick={onSend} disabled={waiting} type="button">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 2L11 13" />
              <path d="M22 2L15 22L11 13L2 9L22 2Z" />
            </svg>
          </button>
          <button
            className="agentspace-fab"
            data-tooltip="打开 Agentspace 编辑器"
            type="button"
            onClick={() => window.open("/agentspace", "_blank")}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
              <path d="M10 13l4-4M14 9h-4v4" />
            </svg>
          </button>
          <button
            className="interrupt-btn"
            onClick={onInterrupt}
            data-tooltip="中断当前 Agent 工作"
            type="button"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          </button>
        </div>
      </div>
    </footer>
  );
}
