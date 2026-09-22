import type { ChatMessage, MessageContent, ToolCardData, ToolCardResult, ToolCardStatus } from "../../types";
import type { HistoryToolCardDto } from "./types";

export function toolCardLiveId(toolCallId: string): string {
  return `tool-card:${toolCallId}`;
}

export function historyToolCardToChatMessage(
  rowId: string,
  historyIndex: number,
  characterName: string | null | undefined,
  card: HistoryToolCardDto,
): ChatMessage {
  const result: ToolCardResult | undefined = card.result_content == null && card.result_history_index == null
    ? undefined
    : {
        content: card.result_content ?? "",
        toolCallMeta: card.tool_call_meta ?? undefined,
        isError: card.is_error,
        historyIndex: card.result_history_index ?? undefined,
      };
  const data: ToolCardData = {
    request: {
      toolCallId: card.tool_call_id,
      toolName: card.tool_name,
      args: card.request_args,
      argsRaw: card.request_args_raw ?? undefined,
    },
    status: card.status,
    result,
  };
  return {
    id: rowId,
    role: "tool",
    content: `${characterName ? `${characterName} ` : ""}⚡ ${card.tool_name}`,
    messageIndex: historyIndex,
    characterName: characterName ?? undefined,
    toolName: card.tool_name,
    toolArgs: card.request_args,
    toolCard: data,
    toolCallMeta: result?.toolCallMeta,
    isError: result?.isError,
  };
}

export function mergeToolCardStatus(
  current: ToolCardStatus | undefined,
  incoming: ToolCardStatus,
): ToolCardStatus {
  if (!current) return incoming;
  if ((current === "succeeded" || current === "failed")
    && (incoming === "running" || incoming === "missing_result")) return current;
  if (current === "running" && incoming === "missing_result") return current;
  return incoming;
}

export function mergeToolCard(
  current: ToolCardData | undefined,
  patch: Partial<ToolCardData> & { request?: Partial<ToolCardData["request"]> },
): ToolCardData {
  const request = {
    ...(current?.request || { toolCallId: patch.request?.toolCallId || "" }),
    ...(patch.request || {}),
  };
  return {
    request,
    status: mergeToolCardStatus(current?.status, patch.status || current?.status || "running"),
    result: patch.result === undefined ? current?.result : patch.result,
  };
}

export function toolCardSummary(card: ToolCardData): string {
  const name = card.request.toolName || "tool";
  const state = card.status === "running"
    ? "执行中"
    : card.status === "succeeded"
      ? "已完成"
      : card.status === "failed"
        ? "失败"
        : "未返回结果";
  return `⚡ ${name} · ${state}`;
}

export function hasVisibleAssistantContent(message: ChatMessage): boolean {
  if (message.role !== "assistant") return true;
  const content = typeof message.content === "string"
    ? message.content
    : message.content.some((block) => block.type === "text" ? block.text.trim() : true);
  return Boolean(content || message.reasoningContent?.trim());
}

export function resultPatch(
  content: MessageContent,
  toolCallMeta?: ToolCardResult["toolCallMeta"],
  extras?: Pick<ToolCardResult, "imageMarkdown" | "downloadInfo" | "isError" | "historyIndex">,
): ToolCardResult {
  return { content, toolCallMeta, ...extras };
}
