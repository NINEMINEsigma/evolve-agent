import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ChatMessage } from "../types";
import MessageItem from "./MessageItem";

afterEach(cleanup);

function ToolBubble({ streaming = false, content = "tool output" }: { streaming?: boolean; content?: string }) {
  const [message, setMessage] = useState<ChatMessage>({ id: "tool-1", role: "tool", content });
  return (
    <MessageItem
      message={message}
      archived={false}
      streaming={streaming}
      onImageClick={() => {}}
      onToggleCollapse={() => setMessage((current) => ({
        ...current,
        collapsed: current.collapsed === false,
      }))}
      onEditMessage={() => {}}
    />
  );
}

describe("MessageItem folding", () => {
  it("only shows the summary control for long tool messages", async () => {
    const user = userEvent.setup();
    const { container } = render(<ToolBubble content={`tool output ${"x".repeat(1300)}`} />);
    const summary = screen.getByRole("button", { name: /tool output/ });
    expect(screen.queryByRole("button", { name: "收起" })).toBeNull();
    expect(screen.queryByRole("button", { name: "展开" })).toBeNull();
    expect(container.querySelector('[data-chat-scope="tool-detail"]')).toBeNull();
    await user.click(summary);
    expect(container.querySelector('[data-chat-scope="tool-detail"]')).not.toBeNull();
  });

  it("keeps the ordinary long-message toolbar control", async () => {
    const user = userEvent.setup();
    const onToggleCollapse = vi.fn();
    const { container } = render(
      <MessageItem
        message={{ id: "user-1", role: "user", content: "x".repeat(1300) }}
        archived={false}
        onImageClick={() => {}}
        onToggleCollapse={onToggleCollapse}
        onEditMessage={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "展开" })).not.toBeNull();
    expect(container.querySelector(".tool-call-summary")).toBeNull();
    await user.click(screen.getByRole("button", { name: "展开" }));
    expect(onToggleCollapse).toHaveBeenCalledWith("user-1");
  });

  it("starts collapsed and toggles tool details during streaming", async () => {
    const user = userEvent.setup();
    const { container } = render(<ToolBubble streaming />);
    const summary = screen.getByRole("button", { name: "tool output" });
    expect(container.querySelector('[data-chat-scope="tool-detail"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "收起" })).toBeNull();
    await user.click(summary);
    expect(container.querySelector('[data-chat-scope="tool-detail"]')).not.toBeNull();
    await user.click(summary);
    expect(container.querySelector('[data-chat-scope="tool-detail"]')).toBeNull();
  });
});
