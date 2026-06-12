import { AskRequest } from "../types";

interface AskDialogProps {
  pendingAsk: AskRequest | null;
  askCustomText: string;
  setAskCustomText: (v: string) => void;
  askSelectedOption: string | null;
  setAskSelectedOption: (v: string | null) => void;
  onRespond: (option?: string, customText?: string) => void;
}

export default function AskDialog({
  pendingAsk,
  askCustomText,
  setAskCustomText,
  askSelectedOption,
  setAskSelectedOption,
  onRespond,
}: AskDialogProps) {
  if (!pendingAsk) return null;

  return (
    <div className="confirm-overlay" onClick={() => {}}>
      <div className="confirm-dialog ask-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="confirm-title">❓ {pendingAsk.question}</div>
        <div className="confirm-body">
          {pendingAsk.options && pendingAsk.options.length > 0 && (
            <div className="ask-options">
              {pendingAsk.options.map((opt) => (
                <button
                  key={opt.value}
                  className={`ask-option-btn ${askSelectedOption === opt.value ? "ask-option-selected" : ""}`}
                  onClick={() => {
                    setAskSelectedOption(opt.value);
                    setAskCustomText("");
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
          {pendingAsk.allow_custom !== false && (
            <textarea
              className="ask-custom-input"
              value={askCustomText}
              onChange={(e) => {
                setAskCustomText(e.target.value);
                if (e.target.value) setAskSelectedOption(null);
              }}
              placeholder="输入自定义内容..."
              rows={3}
            />
          )}
        </div>
        <div className="confirm-actions">
          <button
            className="confirm-deny"
            onClick={() => onRespond(undefined, undefined)}
          >
            跳过
          </button>
          <button
            className="confirm-always"
            disabled={!askSelectedOption && !askCustomText.trim()}
            onClick={() => onRespond(askSelectedOption ?? undefined, askCustomText.trim() || undefined)}
          >
            提交
          </button>
        </div>
      </div>
    </div>
  );
}