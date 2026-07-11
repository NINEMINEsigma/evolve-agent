export function getToolTitle(tool?: string): string {
  if (!tool) return "确认执行命令";
  const label = TOOL_LABELS.find(([key]) => tool.includes(key));
  return label ? label[1] : `确认执行: ${tool}`;
}

const TOOL_LABELS: Array<[string, string]> = [
  ["command", "确认执行命令"],
  ["shell", "确认执行命令"],
  ["python", "确认运行 Python"],
  ["file", "确认文件操作"],
  ["edit", "确认文件操作"],
  ["write", "确认文件操作"],
  ["frontend", "确认前端操作"],
  ["code", "确认代码操作"],
  ["web_search", "确认网络搜索"],
  ["web_fetch", "确认获取网页"],
  ["browser", "确认浏览器操作"],
  ["ssh", "确认 SSH 操作"],
  ["pip", "确认安装依赖"],
  ["install", "确认安装依赖"],
  ["cron", "确认定时任务"],
  ["display", "确认展示内容"],
  ["image", "确认读取图片"],
  ["excel", "确认 Excel 操作"],
  ["docx", "确认 Word 操作"],
  ["pdf", "确认 PDF 操作"],
  ["csv", "确认 CSV 操作"],
  ["ffmpeg", "确认 FFmpeg 操作"],
  ["diagram", "确认图表操作"],
  ["mermaid", "确认 Mermaid 操作"],
  ["gui", "确认 GUI 操作"],
];