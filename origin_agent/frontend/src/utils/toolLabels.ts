export function getToolTitle(tool?: string): string {
  if (!tool) return "确认执行命令";
  const label = TOOL_LABELS.find(([key]) => tool.includes(key));
  return label ? label[1] : `确认执行: ${tool}`;
}

const TOOL_LABELS: Array<[string, string]> = [
  ["Command", "确认执行命令"],
  ["Python", "确认运行 Python"],
  ["File", "确认文件操作"],
  ["Edit", "确认文件操作"],
  ["Write", "确认文件操作"],
  ["Frontend", "确认前端操作"],
  ["Code", "确认代码操作"],
  ["WebSearch", "确认网络搜索"],
  ["WebFetch", "确认获取网页"],
  ["Browser", "确认浏览器操作"],
  ["Install", "确认安装依赖"],
  ["Cron", "确认定时任务"],
  ["Display", "确认展示内容"],
];