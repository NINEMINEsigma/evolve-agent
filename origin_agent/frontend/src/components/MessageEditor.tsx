import { useState, useEffect } from "react";
import { ChatMessage } from "../types";
import { contentToText } from "./MessageBody";

interface MessageEditorProps {
  message: ChatMessage;
  onSave: (content: string) => void | Promise<void>;
  onCancel: () => void;
}

export default function MessageEditor({ message, onSave, onCancel }: MessageEditorProps) {
  const initialText = contentToText(message.content);
  const [draft, setDraft] = useState(initialText);

  useEffect(() => {
    setDraft(initialText);
  }, [initialText]);

  const handleSave = async () => {
    const next = draft.trimEnd();
    if (next === initialText) {
      onCancel();
      return;
    }
    await onSave(next);
  };

  return (
    <div className="message-edit-box">
      <textarea
        className="message-edit-textarea"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={Math.min(Math.max(draft.split("\n").length, 4), 18)}
      />
      <div className="message-edit-actions">
        <button type="button" onClick={handleSave}>保存</button>
        <button type="button" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}