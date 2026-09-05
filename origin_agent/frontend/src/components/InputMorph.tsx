import { useEffect, useState } from "react";
import JsonView from "react18-json-view";
import "react18-json-view/src/style.css";
import { AskRequest, ConfirmRequest } from "../types";
import { getToolTitle } from "../utils/toolLabels";
import MarkdownRenderer from "./primitives/MarkdownRenderer";

// 变形条目：confirm 优先于 ask 显示（由 InputBar 计算）
export type MorphItem =
  | { kind: "ask"; ask: AskRequest }
  | { kind: "confirm"; confirm: ConfirmRequest };

interface InputMorphProps {
  item: MorphItem;
  /** 队列中除当前条目外的待处理数量 */
  queueExtra: number;
  /** RichInput 当前纯文本（ask=回答草稿，confirm=拒绝理由草稿） */
  inputText: string;
  onRespondAsk: (ask: AskRequest, option?: string, customText?: string) => void;
  onRespondConfirm: (confirm: ConfirmRequest, action: string, reason?: string) => void;
  /** 点选选项时清空输入框，维持选项/自定义文本互斥 */
  onClearInput: () => void;
}

export default function InputMorph({
  item,
  queueExtra,
  inputText,
  onRespondAsk,
  onRespondConfirm,
  onClearInput,
}: InputMorphProps) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const itemId = item.kind === "ask" ? item.ask.request_id : item.confirm.request_id;

  // 新条目出现时重置选中态并自动展开，确保用户注意到新交互
  useEffect(() => {
    setSelectedOption(null);
    setCollapsed(false);
  }, [itemId]);

  const trimmedInput = inputText.trim();
  // 互斥的另一半：输入文本时清除已选选项
  useEffect(() => {
    if (trimmedInput) setSelectedOption(null);
  }, [trimmedInput]);

  const header =
    item.kind === "ask"
      ? `❓ ${item.ask.question}`
      : `⚡ ${getToolTitle(item.confirm.tool)}`;

  // confirm 参数：剔除 reason 后供 JsonView 渲染（reason 已在独立行展示，避免重复）
  const confirmArgs = item.kind === "confirm"
    ? Object.fromEntries(Object.entries(item.confirm.args ?? {}).filter(([k]) => k !== "reason"))
    : {};
  const hasConfirmArgs = Object.keys(confirmArgs).length > 0;

  return (
    <div className="input-morph">
      <div className="input-morph-header">
        <span className="input-morph-title">{header}</span>
        {queueExtra > 0 && (
          <span className="input-morph-queue-badge" data-tooltip={`还有 ${queueExtra} 个待处理`}>
            +{queueExtra}
          </span>
        )}
        <button
          type="button"
          className="input-morph-collapse-btn"
          data-tooltip={collapsed ? "展开详情" : "收起详情（查看上下文）"}
          onClick={() => setCollapsed((v) => !v)}
        >
          {collapsed ? "▲" : "▼"}
        </button>
      </div>

      {!collapsed && (
      <div className="input-morph-body">
        {item.kind === "ask" ? (
          <>
            {item.ask.detail && (
              <div className="input-morph-detail">
                <MarkdownRenderer content={item.ask.detail} />
              </div>
            )}
            {item.ask.options && item.ask.options.length > 0 && (
              <div className="input-morph-options">
                {item.ask.options.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`morph-option-chip ${selectedOption === opt.value ? "selected" : ""}`}
                    onClick={() => {
                      setSelectedOption(opt.value);
                      onClearInput();
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {hasConfirmArgs && (
              <div className="tool-json-view">
                <JsonView
                  src={confirmArgs}
                  collapsed={false}
                  displaySize
                  collapseStringsAfterLength={99999}
                />
              </div>
            )}
            {item.confirm.reason && (
              <div className="input-morph-confirm-reason">原因: {item.confirm.reason}</div>
            )}
          </>
        )}
      </div>
      )}

      <div className="input-morph-actions">
        {item.kind === "ask" ? (
          <>
            <button
              type="button"
              className="morph-btn morph-btn--secondary"
              onClick={() => onRespondAsk(item.ask)}
            >
              跳过
            </button>
            <button
              type="button"
              className="morph-btn morph-btn--primary"
              disabled={!selectedOption && !trimmedInput}
              onClick={() => onRespondAsk(item.ask, selectedOption ?? undefined, trimmedInput || undefined)}
            >
              提交
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="morph-btn morph-btn--secondary"
              onClick={() => onRespondConfirm(item.confirm, "deny", trimmedInput || "用户不同意工具调用")}
            >
              拒绝
            </button>
            <button
              type="button"
              className="morph-btn morph-btn--neutral"
              onClick={() => onRespondConfirm(item.confirm, "allow_once")}
            >
              允许一次
            </button>
            {item.confirm.danger_level !== "critical" && (
              <button
                type="button"
                className="morph-btn morph-btn--primary"
                onClick={() => onRespondConfirm(item.confirm, "allow_always")}
              >
                始终允许
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}