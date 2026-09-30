export function hasMountedChatList(): boolean {
  if (typeof document === "undefined") return false;
  const list = document.querySelector<HTMLElement>(".chat-area .chat-content");
  return Boolean(list?.isConnected);
}

export function hasMountedLiveFooter(): boolean {
  return hasMountedChatList();
}

export function liveBubbleIntersectsViewport(
  root: HTMLElement | null,
  renderId: string,
): boolean {
  const scope = root || (typeof document !== "undefined" ? document : null);
  const bubble = Array.from(scope?.querySelectorAll<HTMLElement>("[data-message-id]") || [])
    .find((element) => element.dataset.messageId === renderId);
  const scroller = bubble?.closest<HTMLElement>(".chat-area");
  if (!scroller || !bubble || !scroller.isConnected || !bubble.isConnected) return false;
  const view = scroller.getBoundingClientRect();
  const box = bubble.getBoundingClientRect();
  return view.width > 0 && view.height > 0 && box.width > 0 && box.height > 0
    && box.left < view.right && box.right > view.left
    && box.top < view.bottom && box.bottom > view.top;
}
