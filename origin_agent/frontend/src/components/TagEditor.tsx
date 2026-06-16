import { useEffect, useRef, useState } from "react";
import { SessionInfo } from "../types";

interface TagEditorProps {
  session: SessionInfo | undefined;
  allTags: string[];
  onClose: () => void;
  onSave: (sid: string, tags: string[]) => void;
}

function validateTag(t: string): { ok: boolean; reason?: string } {
  const s = t.trim();
  if (!s) return { ok: false };
  if (/\s/.test(s)) return { ok: false, reason: "标签不能包含空格" };
  const zh = /^[\u4e00-\u9fa5]{1,5}$/.test(s);
  const en = /^[a-zA-Z]{1,10}$/.test(s);
  if (zh || en) return { ok: true };
  return { ok: false, reason: "仅限 1-5 个汉字 或 1-10 个英文字母" };
}

export default function TagEditor({ session, allTags, onClose, onSave }: TagEditorProps) {
  const [draft, setDraft] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(session?.tags ? [...session.tags] : []);
    setInput("");
    setError(null);
  }, [session?.id, session?.tags]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  if (!session) return null;

  const addTag = (raw: string) => {
    const candidates = raw
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const next = [...draft];
    for (const t of candidates) {
      const check = validateTag(t);
      if (!check.ok) {
        setError(check.reason || "无效标签");
        return;
      }
      if (!next.includes(t)) {
        next.push(t);
      }
    }
    setDraft(next);
    setInput("");
    setError(null);
  };

  const removeTag = (t: string) => {
    setDraft(draft.filter((x) => x !== t));
  };

  const availableSuggestions = allTags.filter((t) => !draft.includes(t));

  return (
    <div className="confirm-overlay" onClick={onClose}>
      <div className="confirm-dialog tag-editor" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-title">编辑标签</div>
        <div className="confirm-body">
          <div className="tag-editor-subtitle">{session.title || session.id.slice(0, 8)}</div>

          <div className="tag-editor-tags">
            {draft.length === 0 && <span className="tag-editor-empty">暂无标签</span>}
            {draft.map((t) => (
              <span key={t} className="tag-editor-tag">
                {t}
                <button onClick={() => removeTag(t)}>×</button>
              </span>
            ))}
          </div>

          <input
            ref={inputRef}
            className="tag-editor-input"
            type="text"
            value={input}
            placeholder="输入标签，按回车或逗号添加"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addTag(input);
              } else if (e.key === "Backspace" && input === "" && draft.length > 0) {
                setDraft(draft.slice(0, -1));
              }
            }}
          />
          {error && <div className="tag-editor-error">{error}</div>}

          {availableSuggestions.length > 0 && (
            <>
              <div className="tag-editor-suggest-title">常用标签</div>
              <div className="tag-editor-suggestions">
                {availableSuggestions.map((t) => (
                  <button key={t} className="tag-editor-suggest-btn" onClick={() => addTag(t)}>
                    + {t}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="confirm-actions">
          <button className="confirm-deny" onClick={onClose}>取消</button>
          <button
            className="confirm-always"
            onClick={() => {
              onSave(session.id, draft);
              onClose();
            }}
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
