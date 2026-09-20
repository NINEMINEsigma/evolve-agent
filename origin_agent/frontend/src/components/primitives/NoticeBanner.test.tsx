import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NoticeBanner from "./NoticeBanner";


describe("NoticeBanner", () => {
  it("renders persistent error and warning notices with an accessible close action", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(
      <NoticeBanner
        notice={{ kind: "error", message: "元数据生成失败" }}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByRole("alert")).toHaveClass("notice-banner-error");
    expect(screen.getByText("元数据生成失败")).toBeInTheDocument();

    rerender(
      <NoticeBanner
        notice={{ kind: "warning", message: "会话已归档，但摘要失败" }}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByRole("alert")).toHaveClass("notice-banner-warning");
    fireEvent.click(screen.getByRole("button", { name: "关闭通知" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
