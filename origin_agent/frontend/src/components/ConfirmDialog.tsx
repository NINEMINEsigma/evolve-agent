import { ConfirmRequest } from "../types";

interface ConfirmDialogProps {
  pendingConfirm: ConfirmRequest | null;
  denyReason: string;
  setDenyReason: (v: string) => void;
  onRespond: (action: string, denyReasonText?: string, deniedBy?: string) => void;
}

export default function ConfirmDialog({
  pendingConfirm,
  denyReason,
  setDenyReason,
  onRespond,
}: ConfirmDialogProps) {
  if (!pendingConfirm) return null;

  const toolTitle = (() => {
    const t = pendingConfirm.tool ?? "";
    if (t.includes("command") || t.includes("shell")) return "确认执行命令";
    if (t.includes("python")) return "确认运行 Python";
    if (t.includes("file") || t.includes("edit") || t.includes("write")) return "确认文件操作";
    if (t.includes("frontend")) return "确认前端操作";
    if (t.includes("code")) return "确认代码操作";
    if (t.includes("web_search")) return "确认网络搜索";
    if (t.includes("web_fetch")) return "确认获取网页";
    if (t.includes("browser")) return "确认浏览器操作";
    if (t.includes("ssh")) return "确认 SSH 操作";
    if (t.includes("pip") || t.includes("install")) return "确认安装依赖";
    if (t.includes("cron")) return "确认定时任务";
    if (t.includes("display")) return "确认展示内容";
    if (t.includes("image")) return "确认读取图片";
    if (t.includes("excel")) return "确认 Excel 操作";
    if (t.includes("docx")) return "确认 Word 操作";
    if (t.includes("pdf")) return "确认 PDF 操作";
    if (t.includes("csv")) return "确认 CSV 操作";
    if (t.includes("ffmpeg")) return "确认 FFmpeg 操作";
    if (t.includes("diagram")) return "确认图表操作";
    if (t.includes("mermaid")) return "确认 Mermaid 操作";
    if (t.includes("gui")) return "确认 GUI 操作";
    if (t) return `确认执行: ${t}`;
    return "确认执行命令";
  })();

  return (
    <div className="confirm-overlay">
      <div className="confirm-dialog">
        <div className="confirm-title">{toolTitle}</div>
        <div className="confirm-body">
          <pre className="confirm-cmd">
            {pendingConfirm.command?.join(" ") ?? pendingConfirm.content}
          </pre>
          {pendingConfirm.reason && (
            <div className="confirm-reason">原因: {pendingConfirm.reason}</div>
          )}
          <textarea
            className="confirm-deny-reason"
            value={denyReason}
            onChange={(e) => setDenyReason(e.target.value)}
            placeholder="输入拒绝原因..."
            rows={2}
          />
        </div>
        <div className="confirm-actions">
          <button
            className="confirm-deny"
            onClick={() => onRespond("deny", denyReason, "user")}>
            拒绝
          </button>
          <button className="confirm-once" onClick={() => onRespond("allow_once")}>
            允许一次
          </button>
          <button className="confirm-always" onClick={() => onRespond("allow_always")}>
            始终允许
          </button>
        </div>
      </div>
    </div>
  );
}