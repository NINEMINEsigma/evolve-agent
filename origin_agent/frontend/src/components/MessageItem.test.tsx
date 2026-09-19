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

  it("keeps the full tool argument summary for CSS width-based truncation", () => {
    const args = { path: "ws:notes/very-long-file-name.txt", content: "x".repeat(160) };
    const fullSummary = `main-agent ⚡ Write ${JSON.stringify(args)}`;
    render(
      <MessageItem
        message={{ id: "tool-call-1", role: "tool", content: "main-agent ⚡ Write", toolName: "Write", toolArgs: args }}
        archived={false}
        onImageClick={() => {}}
        onToggleCollapse={() => {}}
        onEditMessage={() => {}}
      />,
    );
    const summary = screen.getByRole("button");
    expect(summary.textContent).toBe(fullSummary);
    expect(summary.getAttribute("title")).toBe(fullSummary);
    expect(summary.querySelector(".tool-call-summary-text")?.className).toBe("tool-call-summary-text");
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

  it("keeps a long assistant reply expanded after streaming ends when selected", () => {
    const message: ChatMessage = {
      id: "reply", role: "assistant", content: "x".repeat(1300), collapsed: false,
    };
    const props = {
      message, archived: false, onImageClick: () => {},
      onToggleCollapse: () => {}, onEditMessage: () => {},
    };
    const { container, rerender } = render(<MessageItem {...props} streaming />);
    rerender(<MessageItem {...props} streaming={false} />);
    expect(container.querySelector(".message-content-collapsed")).toBeNull();
    expect(screen.getByRole("button", { name: "收起" })).not.toBeNull();
  });
});
