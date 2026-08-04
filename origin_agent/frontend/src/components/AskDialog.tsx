import { AskRequest } from "../types";
import ModalWindow from "./primitives/ModalWindow";

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
    <ModalWindow
      className="ask-dialog"
      title={`❓ ${pendingAsk.question}`}
      actions={
        <>
          <button
            className="modal-btn modal-btn--secondary"
            onClick={() => onRespond(undefined, undefined)}
          >
            跳过
          </button>
          <button
            className="modal-btn modal-btn--primary"
            disabled={!askSelectedOption && !askCustomText.trim()}
            onClick={() => onRespond(askSelectedOption ?? undefined, askCustomText.trim() || undefined)}
          >
            提交
          </button>
        </>
      }
    >
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
    </ModalWindow>
  );
}