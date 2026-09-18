export function hasMountedLiveFooter(): boolean {
  if (typeof document === "undefined") return false;
  const footer = document.querySelector<HTMLElement>(".chat-area .chat-live-footer");
  return Boolean(footer?.isConnected);
}

export function liveBubbleIntersectsViewport(
  footer: HTMLElement,
  streamId: string,
): boolean {
  const scroller = footer.closest<HTMLElement>(".chat-area");
  const bubble = Array.from(footer.querySelectorAll<HTMLElement>("[data-message-id]"))
    .find((element) => element.dataset.messageId === streamId);
  if (!scroller || !bubble || !scroller.isConnected || !bubble.isConnected) return false;
  const view = scroller.getBoundingClientRect();
  const box = bubble.getBoundingClientRect();
  return view.width > 0 && view.height > 0 && box.width > 0 && box.height > 0
    && box.left < view.right && box.right > view.left
    && box.top < view.bottom && box.bottom > view.top;
}
