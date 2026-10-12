import { useEffect, useRef, useState } from "react";
import JsonView from "react18-json-view";
import "react18-json-view/src/style.css";
import { AskAnswerItem, AskRequest, AskQuestionItem, ConfirmRequest } from "../types";
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
  /** RichInput 当前纯文本（ask=当前题回答草稿，confirm=拒绝理由草稿） */
  inputText: string;
  /** ask 分页：按题保存的草稿字典（不含当前题，当前题实时草稿走 inputText） */
  drafts: Record<number, string>;
  /** ask 分页：请求切换到指定题（InputBar 负责保存/恢复草稿） */
  onGoToQuestion: (index: number) => void;
  onRespondAsk: (ask: AskRequest, answers: AskAnswerItem[] | null) => void;
  onRespondConfirm: (confirm: ConfirmRequest, action: string, reason?: string) => void;
}

export default function InputMorph({
  item,
  queueExtra,
  inputText,
  drafts,
  onGoToQuestion,
  onRespondAsk,
  onRespondConfirm,
}: InputMorphProps) {
  // ask 分页向导状态：当前题索引 + 按题选中 chips
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedByQuestion, setSelectedByQuestion] = useState<Record<number, string[]>>({});
  const [collapsed, setCollapsed] = useState(false);
  // 跑马灯：标题溢出时启动自动滚动
  const [titleMarquee, setTitleMarquee] = useState(false);
  const titleRef = useRef<HTMLSpanElement>(null);
  const itemId = item.kind === "ask" ? item.ask.request_id : item.confirm.request_id;

  const questions: AskQuestionItem[] = item.kind === "ask" ? item.ask.questions : [];
  const currentIndex = item.kind === "ask" && pageIndex < questions.length ? pageIndex : 0;
  const currentQuestion: AskQuestionItem | undefined = questions[currentIndex];
  const trimmedInput = inputText.trim();

  // 新表单/新确认到达时重置分页、选中态、展开态，确保用户注意到新交互
  useEffect(() => {
    setPageIndex(0);
    setSelectedByQuestion({});
    setCollapsed(false);
  }, [itemId]);

  // 分页切换后重新检测标题溢出（题号或内容变化均需重测）
  useEffect(() => {
    setTitleMarquee(false);
    if (item.kind !== "ask" || !currentQuestion) return;
    const el = titleRef.current;
    if (!el) return;
    const overflow = el.scrollWidth > el.clientWidth + 1;
    setTitleMarquee(overflow);
  }, [item.kind, itemId, currentIndex, currentQuestion?.question]);

  if (item.kind === "ask") {
    if (!currentQuestion) return null;
    // ── ask 分支：分页向导 ──
    const selected = selectedByQuestion[currentIndex] ?? [];
    const multiSelect = currentQuestion.multi_select === true;
    const isLast = currentIndex === questions.length - 1;

    const chipClick = (value: string) => {
      setSelectedByQuestion((prev) => {
        const current = prev[currentIndex] ?? [];
        if (multiSelect) {
          const next = current.includes(value)
            ? current.filter((v) => v !== value)
            : [...current, value];
          return { ...prev, [currentIndex]: next };
        }
        // 单选：点已选项取消，点其他项替换
        const next = current.includes(value) ? [] : [value];
        return { ...prev, [currentIndex]: next };
      });
    };

    // 分页切换：先同步自身题号，再通知 InputBar 保存/恢复草稿
    const goTo = (next: number) => {
      if (next < 0 || next > questions.length - 1) return;
      setPageIndex(next);
      onGoToQuestion(next);
    };

    // 某题是否已作答：当前题看实时草稿 inputText，其他题看草稿字典与选中集
    const isAnswered = (index: number): boolean => {
      if (index === currentIndex) {
        return trimmedInput.length > 0 || (selectedByQuestion[index]?.length ?? 0) > 0;
      }
      return (selectedByQuestion[index]?.length ?? 0) > 0 || (drafts[index]?.trim().length ?? 0) > 0;
    };

    // 收集整表答案：当前题 custom_text 取实时草稿，其余题取草稿字典
    const collectAnswers = (): AskAnswerItem[] => {
      return questions.map((_, index) => {
        if (index === currentIndex) {
          return {
            selected: selectedByQuestion[index] ?? [],
            custom_text: trimmedInput ? trimmedInput : null,
          };
        }
        return {
          selected: selectedByQuestion[index] ?? [],
          custom_text: drafts[index]?.trim() ? drafts[index].trim() : null,
        };
      });
    };

    const titleText = `❓ ${currentQuestion.question}`;
    // 跑马灯态渲染双份文本衔接实现无缝循环（动画 translateX 0 → -50%）
    const marqueeText = titleMarquee ? `${titleText}　${titleText}` : titleText;

    return (
      <div className="input-morph">
        <div className="input-morph-header">
          {questions.length > 1 && (
            <button
              type="button"
              className="input-morph-pager-btn"
              data-tooltip="上一题"
              disabled={currentIndex === 0}
              onClick={() => goTo(currentIndex - 1)}
            >
              ◀
            </button>
          )}
          <span
            ref={titleRef}
            className={`input-morph-title ${titleMarquee ? "marquee" : ""}`}
            data-tooltip={currentQuestion.question}
          >
            {marqueeText}
          </span>
          {questions.length > 1 && (
            <>
              <span className={`input-morph-pager-index ${isAnswered(currentIndex) ? "answered" : ""}`}>
                {currentIndex + 1}/{questions.length}
              </span>
              <button
                type="button"
                className="input-morph-pager-btn"
                data-tooltip="下一题"
                disabled={currentIndex === questions.length - 1}
                onClick={() => goTo(currentIndex + 1)}
              >
                ▶
              </button>
            </>
          )}
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
          {currentQuestion.detail && (
            <div className="input-morph-detail">
              <MarkdownRenderer content={currentQuestion.detail} />
            </div>
          )}
          {currentQuestion.options && currentQuestion.options.length > 0 && (
            <div className="input-morph-options">
              {currentQuestion.options.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`morph-option-chip ${selected.includes(opt.value) ? "selected" : ""}`}
                  data-tooltip={multiSelect ? "多选：点击切换选中" : undefined}
                  onClick={() => chipClick(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>
        )}

        <div className="input-morph-actions">
          {isLast ? (
            <>
              <button
                type="button"
                className="morph-btn morph-btn--secondary"
                onClick={() => onRespondAsk(item.ask, null)}
              >
                跳过
              </button>
              <button
                type="button"
                className="morph-btn morph-btn--primary"
                onClick={() => onRespondAsk(item.ask, collectAnswers())}
              >
                提交
              </button>
            </>
          ) : (
            <button
              type="button"
              className="morph-btn morph-btn--primary"
              onClick={() => goTo(currentIndex + 1)}
            >
              下一题
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── confirm 分支：保持原有行为 ──
  const confirmArgs = Object.fromEntries(
    Object.entries(item.confirm.args ?? {}).filter(([k]) => k !== "reason"),
  );
  const hasConfirmArgs = Object.keys(confirmArgs).length > 0;

  return (
    <div className="input-morph">
      <div className="input-morph-header">
        <span
          ref={titleRef}
          className="input-morph-title"
          data-tooltip={getToolTitle(item.confirm.tool)}
        >
          {`⚡ ${getToolTitle(item.confirm.tool)}`}
        </span>
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
        {item.confirm.reason && (
          <div className="input-morph-confirm-reason">原因: {item.confirm.reason}</div>
        )}
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
      </div>
      )}

      <div className="input-morph-actions">
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
      </div>
    </div>
  );
}
