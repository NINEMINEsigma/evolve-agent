import type { ChatMessage, MessageContent } from "../../types";
import { DIMENSIONS } from "../../constants/dimensions";

export function contentToText(content: MessageContent): string {
  if (typeof content === "string") return content;
  return content
    .map((block) => (block.type === "text" ? block.text : block.type === "image_url" ? "[image_url]" : block.type === "input_audio" ? "[input_audio]" : block.type === "video_url" ? "[video_url]" : ""))
    .join("\n");
}

export function isLongChatMessage(message: ChatMessage): boolean {
  const text = contentToText(message.content);
  return text.length > DIMENSIONS.LONG_MESSAGE_CHARS
    || text.split("\n").length > DIMENSIONS.LONG_MESSAGE_LINES;
}

export function toolCallSummary(message: ChatMessage): string {
  const content = contentToText(message.content);
  if (!message.toolArgs) return content;
  try {
    const args = JSON.stringify(message.toolArgs);
    return args === undefined ? content : `${content} ${args}`;
  } catch {
    return content;
  }
}
