import { SessionInfo } from "../types";

interface InputBarProps {
  input: string;
  setInput: (v: string) => void;
  waiting: boolean;
  uploading: boolean;
  sessionId: string;
  sessions: SessionInfo[];
  onSend: () => void;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onUploadClick: () => Promise<void>;
  onInterrupt: () => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
}

export default function InputBar({
  input,
  setInput,
  waiting,
  uploading,
  sessionId,
  sessions,
  onSend,
  onUpload,
  onUploadClick,
  onInterrupt,
  fileInputRef,
}: InputBarProps) {
  const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";

  return (
    <footer className="input-bar">
      {isArchived ? (
        <div className="archived-notice">此会话已归档，无法发送消息</div>
      ) : (
        <div className="input-bar-inner">
          <div className="input-bar-row">
            <textarea
              className="input-field"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSend();
                }
              }}
              onInput={(e) => {
                const el = e.currentTarget;
                el.style.height = "auto";
                el.style.height = el.scrollHeight + "px";
              }}
              placeholder="输入消息..."
              autoFocus
              disabled={waiting}
              rows={1}
            />
            <input
              ref={fileInputRef}
              type="file"
              className="file-input-hidden"
              onChange={onUpload}
              multiple
              disabled={uploading}
            />
            <button
              className="upload-btn"
              onClick={onUploadClick}
              disabled={uploading}
              title="上传文件"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </button>
            <button className="send-btn" onClick={onSend} disabled={waiting || !input.trim()}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
              </svg>
            </button>
            {waiting && (
              <button
                className="interrupt-btn"
                onClick={onInterrupt}
              >
                ⏹
              </button>
            )}
          </div>
        </div>
      )}
    </footer>
  );
}