import { useEffect, type RefObject } from "react";

const CHARACTER_MESSAGE_SELECTOR = '[data-chat-scope="message"][data-character-name]';

function findCharacterMessage(target: EventTarget | null, root: HTMLDivElement): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  const message = target.closest<HTMLElement>(CHARACTER_MESSAGE_SELECTOR);
  return message && root.contains(message) ? message : null;
}

/**
 * 主聊天区的同角色悬停联动。
 *
 * 直接维护公开 data 属性，避免把瞬时悬停状态送入 React 消息树，
 * 从而避免长会话中全部历史 MessageItem 因一次悬停而重新渲染。
 */
export function useMessageCharacterHover(contentRef: RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const root = contentRef.current;
    if (!root) return;

    let activeCharacterName: string | null = null;

    const applyCharacter = (characterName: string | null) => {
      if (activeCharacterName === characterName) return;
      activeCharacterName = characterName;

      root.querySelectorAll<HTMLElement>(CHARACTER_MESSAGE_SELECTOR).forEach((message) => {
        if (characterName !== null && message.dataset.characterName === characterName) {
          message.setAttribute("data-character-hovered", "true");
        } else {
          message.removeAttribute("data-character-hovered");
        }
      });
    };

    const onMouseOver = (event: MouseEvent) => {
      const message = findCharacterMessage(event.target, root);
      if (!message) return;
      if (event.relatedTarget instanceof Node && message.contains(event.relatedTarget)) return;
      applyCharacter(message.dataset.characterName || null);
    };

    const onMouseOut = (event: MouseEvent) => {
      const message = findCharacterMessage(event.target, root);
      if (!message) return;
      if (event.relatedTarget instanceof Node && message.contains(event.relatedTarget)) return;

      const nextMessage = findCharacterMessage(event.relatedTarget, root);
      applyCharacter(nextMessage?.dataset.characterName || null);
    };

    const onMouseLeave = () => applyCharacter(null);

    root.addEventListener("mouseover", onMouseOver);
    root.addEventListener("mouseout", onMouseOut);
    root.addEventListener("mouseleave", onMouseLeave);

    return () => {
      root.removeEventListener("mouseover", onMouseOver);
      root.removeEventListener("mouseout", onMouseOut);
      root.removeEventListener("mouseleave", onMouseLeave);
      activeCharacterName = null;
      root.querySelectorAll<HTMLElement>(CHARACTER_MESSAGE_SELECTOR).forEach((message) => {
        message.removeAttribute("data-character-hovered");
      });
    };
  }, [contentRef]);
}
