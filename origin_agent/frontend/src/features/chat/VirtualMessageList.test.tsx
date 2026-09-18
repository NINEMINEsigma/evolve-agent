import { act, cleanup, render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VirtualMessageList from "./VirtualMessageList";
import { resetChatRuntimeStoreForTest, useChatRuntimeStore } from "./chatRuntimeStore";
import { hasMountedLiveFooter } from "./chatViewport";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const followAfterLiveCommit = vi.hoisted(() => vi.fn());

vi.mock("react-virtuoso", async () => {
  const React = await import("react");
  return {
    Virtuoso: React.forwardRef<HTMLDivElement, {
      components: { Footer: ComponentType<{ context: unknown }> };
      context: unknown;
    }>(function MockVirtuoso({ components: { Footer }, context }, ref) {
      return <div ref={ref} className="chat-area"><Footer context={context} /></div>;
    }),
  };
});

vi.mock("./useChatScrollController", () => ({
  useChatScrollController: () => ({
    followAfterLiveCommit,
    beginUserHeightMutation: vi.fn(),
    returnToBottom: vi.fn(),
    beginMinimapDrag: vi.fn(),
    previewMinimapScrollTop: vi.fn(),
    commitMinimapDrag: vi.fn(),
    handleRangeChanged: vi.fn(),
    handleAtBottomStateChange: vi.fn(),
    handleTotalListHeightChanged: vi.fn(),
  }),
}));

vi.mock("../../components/MessageItem", () => ({
  default: ({ message, streaming }: { message: { id: string; collapsed?: boolean }; streaming?: boolean }) => (
    <div data-testid="live-bubble" data-message-id={message.id} data-streaming={String(Boolean(streaming))}
      data-collapsed={String(message.collapsed)} />
  ),
}));

vi.mock("../../hooks/useMessageCharacterHover", () => ({
  useMessageCharacterHover: () => {},
}));

describe("live message layout follow", () => {
  beforeEach(() => {
    resetChatRuntimeStoreForTest();
    useChatRuntimeStore.getState().setInitialReady(true);
    followAfterLiveCommit.mockClear();
  });

  it("requests a pre-paint follow when a short live bubble appears and grows", () => {
    render(
      <VirtualMessageList
        archived={false}
        onImageClick={() => {}}
        onEditMessage={() => {}}
        onDeleteMessages={() => {}}
        onRegenerateResponse={() => {}}
        onDropFiles={() => {}}
      />,
    );
    followAfterLiveCommit.mockClear();

    act(() => {
      useChatRuntimeStore.getState().appendLiveMessage(
        { id: "live", role: "assistant", content: "short" }, true,
      );
    });
    expect(screen.getByTestId("live-bubble")).toBeTruthy();
    expect(followAfterLiveCommit).toHaveBeenCalledTimes(1);

    act(() => useChatRuntimeStore.getState().finishStream("live", "a longer reply"));
    expect(followAfterLiveCommit).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["fully visible", 10, 80, true],
    ["partly visible", 90, 140, true],
    ["touching the edge", 100, 150, false],
    ["outside", 120, 160, false],
    ["zero height", 50, 50, false],
  ] as const)("samples %s when the stream ends", (_name, top, bottom, expected) => {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const isScroller = this.classList.contains("chat-area");
      const y = isScroller ? 0 : top;
      const lower = isScroller ? 100 : bottom;
      return {
        x: 0, y, top: y, bottom: lower, left: 0, right: 200,
        width: 200, height: lower - y, toJSON: () => ({}),
      } as DOMRect;
    });
    render(
      <VirtualMessageList
        archived={false} onImageClick={() => {}} onEditMessage={() => {}}
        onDeleteMessages={() => {}} onRegenerateResponse={() => {}} onDropFiles={() => {}}
      />,
    );
    expect(hasMountedLiveFooter()).toBe(true);
    act(() => {
      useChatRuntimeStore.getState().appendLiveMessage(
        { id: "visible", role: "assistant", content: "x".repeat(1300) }, true,
      );
      useChatRuntimeStore.getState().queueStreamFinish("visible", "x".repeat(1300));
    });
    expect(useChatRuntimeStore.getState().liveRows[0].streaming).toBe(false);
    expect(useChatRuntimeStore.getState().liveRows[0].preserveExpanded === true).toBe(expected);
    expect(useChatRuntimeStore.getState().pendingStreamFinishes).toEqual({});
  });

  it("treats an unmounted footer as invisible", () => {
    expect(hasMountedLiveFooter()).toBe(false);
  });
});
