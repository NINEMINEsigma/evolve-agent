/** 仅筛选 system 角色的用户消息，保留系统状态、错误与工具消息。 */
export function isMessageVisible(
  role: string,
  characterName: string | null | undefined,
  showSystemUserMessages: boolean,
): boolean {
  return showSystemUserMessages || role !== "user" || characterName !== "system";
}
