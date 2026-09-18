import { act, render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VirtualMessageList from "./VirtualMessageList";
import { resetChatRuntimeStoreForTest, useChatRuntimeStore } from "./chatRuntimeStore";

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
  default: () => <div data-testid="live-bubble" />,
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
});
