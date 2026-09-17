import { expect, test, type Page } from "@playwright/test";

const sessionId = "test-session";

function makeSkeleton(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    row_id: `history:${index}:message`,
    history_index: index,
    row_kind: "message",
    role: index % 2 === 0 ? "user" : "assistant",
    character_name: index % 2 === 0 ? "end-user" : "main-agent",
    is_system_status: false,
  }));
}

function makeRows(start: number, end: number, contentForIndex?: (index: number) => string) {
  return Array.from({ length: end - start }, (_, offset) => {
    const index = start + offset;
    return {
      row_id: `history:${index}:message`,
      history_index: index,
      row_kind: "message",
      role: index % 2 === 0 ? "user" : "assistant",
      character_name: index % 2 === 0 ? "end-user" : "main-agent",
      is_system_status: false,
      content: contentForIndex?.(index) ?? `message-${index}`,
    };
  });
}

async function mockChat(
  page: Page,
  count = 10_000,
  contentForIndex?: (index: number) => string,
  olderPageDelayMs = 0,
) {
  await page.addInitScript(() => localStorage.setItem("evolve_active_llm_profile", JSON.stringify("test")));
  const skeleton = makeSkeleton(count);
  const pageRequests: string[] = [];
  let serverSocket: { send: (message: string) => void } | null = null;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/history/skeleton")) {
      const start = Number(url.searchParams.get("start_index") || 0);
      await route.fulfill({ json: {
        session_id: sessionId,
        start_index: start,
        history_count: count,
        row_count: count - start,
        rows: skeleton.slice(start),
      } });
      return;
    }
    if (url.pathname.endsWith("/history/page")) {
      pageRequests.push(url.search);
      const start = Number(url.searchParams.get("start_index") || 0);
      const limit = Number(url.searchParams.get("limit") || 80);
      if (olderPageDelayMs > 0 && start < count - 80) {
        await new Promise<void>((resolve) => setTimeout(resolve, olderPageDelayMs));
      }
      await route.fulfill({ json: {
        session_id: sessionId,
        start_index: start,
        end_index: Math.min(count, start + limit),
        history_count: count,
        rows: makeRows(start, Math.min(count, start + limit), contentForIndex),
      } });
      return;
    }
    if (url.pathname.endsWith("/history/resources")) {
      await route.fulfill({ json: {
        session_id: sessionId,
        history_count: count,
        images: [{ resource_id: "image", url: "/mock.png", alt: "mock" }],
        downloads: [],
      } });
      return;
    }
    if (url.pathname.endsWith("/status")) {
      await route.fulfill({ json: { occupied: false } });
      return;
    }
    if (url.pathname.endsWith("/approval/profile")) {
      await route.fulfill({ json: { profile_name: null, model: null, available: false } });
      return;
    }
    if (url.pathname.endsWith("/llm/profiles")) {
      await route.fulfill({ json: { profiles: [{
        name: "test",
        llm_client_name: "openai",
        base_url: "http://example.invalid",
        model: "test-model",
        api_key: "",
        temperature: 0,
        max_output_tokens: 1024,
        reasoning_effort: "",
        max_context_tokens: 8192,
        vision_image_profile: null,
        audio_profile: null,
        vision_video_profile: null,
        soul_file: "SOUL.md",
      }] } });
      return;
    }
    if (url.pathname.endsWith("/sessions")) {
      await route.fulfill({ json: { sessions: [{ id: sessionId, status: "active", created_at: 0 }] } });
      return;
    }
    if (url.pathname.endsWith("/tags")) {
      await route.fulfill({ json: { tags: [] } });
      return;
    }
    await route.fulfill({ json: {} });
  });

  await page.routeWebSocket("**/ws/chat**", (socket) => {
    serverSocket = socket;
    socket.send(JSON.stringify({ type: "system", session_id: sessionId, content: "Connected to Evolve Agent" }));
    socket.send(JSON.stringify({
      type: "history_sync",
      session_id: sessionId,
      history_count: count,
      processing: false,
      token_usage: 0,
      context_tokens: 0,
    }));
    socket.onMessage((message) => {
      const parsed = JSON.parse(String(message));
      if (parsed.type === "ping") socket.send(JSON.stringify({ type: "pong", session_id: sessionId }));
      if (parsed.type === "user_message") {
        socket.send(JSON.stringify({
          type: "user_message",
          session_id: sessionId,
          content: parsed.content,
          client_message_id: parsed.client_message_id,
          index: count,
          character_name: "end-user",
        }));
      }
    });
  });
  return {
    pageRequests,
    sendServer: (message: unknown) => {
      if (!serverSocket) throw new Error("WebSocket is not connected");
      serverSocket.send(JSON.stringify(message));
    },
  };
}

test("流式期间脱离底部后不被拉回，回底后恢复追随", async ({ page }) => {
  const { sendServer } = await mockChat(page, 500);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-499")).toBeVisible();
  await page.locator(".chat-area").hover();
  await page.mouse.wheel(0, -1200);
  sendServer({ type: "stream_delta", session_id: sessionId, stream_id: "stream", delta: "live-text" });
  await expect(page.getByText("live-text")).not.toBeInViewport();
  await page.locator(".scroll-to-bottom").click();
  await expect(page.getByText("live-text")).toBeInViewport();
});

test("流式结束等待正典同步时保留 live 行", async ({ page }) => {
  const { sendServer } = await mockChat(page, 20);
  await page.goto(`/?session=${sessionId}`);
  sendServer({ type: "stream_delta", session_id: sessionId, stream_id: "stream", delta: "frozen-live" });
  sendServer({ type: "stream_done", session_id: sessionId, stream_id: "stream", content: "frozen-live" });
  await expect(page.getByText("frozen-live")).toBeVisible();
});

test("资源抽屉读取完整 History 资源索引", async ({ page }) => {
  await mockChat(page, 100);
  await page.goto(`/?session=${sessionId}`);
  await page.locator('[data-tour="resource-trigger"]').click();
  await expect(page.getByText("图片 (1)")).toBeVisible();
});

test("万行骨架首次显示最新位置且 DOM 有界", async ({ page }) => {
  await mockChat(page);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-9999")).toBeVisible();
  expect(await page.locator("[data-history-row-id]").count()).toBeLessThan(200);
});

test("Minimap 物理高亮与滚动容器尺寸一致", async ({ page }) => {
  await mockChat(page, 1000);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-999")).toBeVisible();
  await expect.poll(async () => page.locator(".minimap-viewport").evaluate((thumb) => {
    const track = thumb.parentElement!;
    const scroller = document.querySelector<HTMLElement>(".chat-area")!;
    const expected = scroller.clientHeight / scroller.scrollHeight * track.clientHeight;
    return Math.abs(thumb.getBoundingClientRect().height - expected);
  })).toBeLessThan(2);
});

test("Minimap 在 25% / 50% / 90% 位置按物理滚动进度跳转", async ({ page }) => {
  await mockChat(page, 1000);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-999")).toBeVisible();
  const box = await page.locator(".minimap").boundingBox();
  if (!box) throw new Error("Minimap not visible");
  for (const progress of [0.25, 0.5, 0.9]) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height * progress);
    await page.mouse.down();
    await page.mouse.up();
    await expect.poll(async () => page.locator(".chat-area").evaluate((scroller) => {
      const max = scroller.scrollHeight - scroller.clientHeight;
      return max > 0 ? scroller.scrollTop / max : 0;
    })).toBeGreaterThan(progress - 0.02);
    const actualProgress = await page.locator(".chat-area").evaluate((scroller) => {
      const max = scroller.scrollHeight - scroller.clientHeight;
      return max > 0 ? scroller.scrollTop / max : 0;
    });
    expect(actualProgress).toBeLessThan(progress + 0.02);
  }
});

test("异构气泡高度变化后 Minimap 仍使用物理比例", async ({ page }) => {
  await mockChat(page, 300, (index) => index % 11 === 0
    ? `message-${index}\n${"long markdown line\n".repeat(80)}`
    : `message-${index}`);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-299")).toBeVisible();
  const before = await page.locator(".minimap-viewport").evaluate((thumb) => thumb.getBoundingClientRect().height);
  await page.locator(".chat-area").evaluate((scroller) => { scroller.scrollTop = 0; });
  await expect(page.getByText("message-0", { exact: false })).toBeVisible();
  await expect.poll(async () => page.locator(".minimap-viewport").evaluate((thumb) => {
    const track = thumb.parentElement!;
    const scroller = document.querySelector<HTMLElement>(".chat-area")!;
    return Math.abs(
      thumb.getBoundingClientRect().height
      - scroller.clientHeight / scroller.scrollHeight * track.clientHeight,
    );
  })).toBeLessThan(2);
  const after = await page.locator(".minimap-viewport").evaluate((thumb) => thumb.getBoundingClientRect().height);
  expect(after).toBeLessThanOrEqual(before);
});

test("Minimap 拖动期间不加载正文，释放后只加载最终范围", async ({ page }) => {
  const { pageRequests } = await mockChat(page, 2000, undefined, 1500);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-1999")).toBeVisible();
  const baseline = pageRequests.length;
  const box = await page.locator(".minimap").boundingBox();
  if (!box) throw new Error("Minimap not visible");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.9);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.25);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.65);
  expect(pageRequests.length).toBe(baseline);
  await page.mouse.up();
  await expect.poll(() => pageRequests.length).toBeGreaterThan(baseline);
});

test("Minimap 释放后加载最终目标且回到底部可用", async ({ page }) => {
  const { pageRequests: requests } = await mockChat(page, 1000);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.getByText("message-999")).toBeVisible();
  const minimap = page.locator(".minimap");
  const box = await minimap.boundingBox();
  if (!box) throw new Error("Minimap not visible");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 12);
  await page.mouse.up();
  await expect.poll(() => requests.some((query) => !query.includes("start_index=920"))).toBeTruthy();
  const button = page.locator(".scroll-to-bottom");
  if (await button.isVisible()) await button.click();
  await expect(page.getByText("message-999")).toBeVisible();
});

test("忙碌时输入仍可编辑且遥测默认关闭", async ({ page }) => {
  await mockChat(page, 100);
  await page.goto(`/?session=${sessionId}`);
  await page.locator(".header-action-btn").first().click();
  await page.getByText("性能遥测").click();
  await expect(page.getByText("已关闭")).toBeVisible();
  await page.getByText("关闭").click();
  const input = page.locator("[contenteditable=true]").first();
  await input.fill("queued while processing");
  await expect(input).toContainText("queued while processing");
  await expect(page.getByText("导出会话")).toHaveCount(0);
});

test("移动端输入栏、回底和 Minimap 控件保持在聊天容器内", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile project only");
  await mockChat(page, 1000);
  await page.goto(`/?session=${sessionId}`);
  await expect(page.locator(".input-bar")).toBeVisible();
  await expect(page.locator(".minimap-toggle")).toBeVisible();
  const inputBox = await page.locator(".input-bar").boundingBox();
  const viewport = page.viewportSize();
  expect(inputBox && viewport && inputBox.y + inputBox.height <= viewport.height).toBeTruthy();
});
