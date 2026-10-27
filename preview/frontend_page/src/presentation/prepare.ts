import { PREVIEW } from "../constants";
import labels from "../content/zh-CN.json";
import type { PreviewOptions } from "../types";

function visible(element: Element | null): element is HTMLElement {
  if (!element) return false;
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
    && rect.top < innerHeight && rect.left < innerWidth
    && style.display !== "none" && style.visibility === "visible";
}

function cancellable<T>(promise: PromiseLike<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const abort = () => { signal.removeEventListener("abort", abort); reject(signal.reason); };
    signal.addEventListener("abort", abort, { once: true });
    Promise.resolve(promise).then(
      (value) => { signal.removeEventListener("abort", abort); if (!signal.aborted) resolve(value); },
      (cause) => { signal.removeEventListener("abort", abort); reject(cause); },
    );
  });
}

function waitFor(check: () => boolean, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    let frame = 0;
    const cleanup = () => { cancelAnimationFrame(frame); signal.removeEventListener("abort", abort); };
    const abort = () => { cleanup(); reject(signal.reason); };
    const poll = () => {
      if (signal.aborted) { abort(); return; }
      try {
        if (check()) { cleanup(); resolve(); return; }
        frame = requestAnimationFrame(poll);
      } catch (cause) { cleanup(); reject(cause); }
    };
    signal.addEventListener("abort", abort, { once: true });
    poll();
  });
}

async function stableLayout(root: Element, signal: AbortSignal): Promise<void> {
  let previous = "";
  let stableFrames = 0;
  await waitFor(() => {
    const nodes = [root, ...root.querySelectorAll("[data-tab-panel], .input-bar, .agentspace-editor, .agentspace-file-tree")].filter(visible);
    const geometry = nodes.map((element) => {
      const rect = element.getBoundingClientRect();
      return [rect.x, rect.y, rect.width, rect.height].map((value) => Math.round(value * 2)).join(",");
    }).join(";");
    stableFrames = geometry === previous ? stableFrames + 1 : 0;
    previous = geometry;
    return stableFrames >= 2;
  }, signal);
}

export async function preparePreviewScene(options: PreviewOptions, signal: AbortSignal): Promise<void> {
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason ?? new DOMException("Preview preparation cancelled", "AbortError"));
  if (signal.aborted) cancel();
  else signal.addEventListener("abort", cancel, { once: true });
  const timeout = window.setTimeout(() => controller.abort(new Error(labels.ui.prepareTimeout)), PREVIEW.prepareTimeoutMs);
  const local = controller.signal;
  const loadedFrames = new WeakSet<HTMLIFrameElement>();
  const failedResources = new WeakSet<Element>();
  const loaded = (event: Event) => { if (event.target instanceof HTMLIFrameElement) loadedFrames.add(event.target); };
  const failed = (event: Event) => { if (event.target instanceof Element) failedResources.add(event.target); };
  document.addEventListener("load", loaded, true);
  document.addEventListener("error", failed, true);
  try {
    local.throwIfAborted();
    let root: Element;
    if (options.editor) {
      // 编辑器路由完全独立，绝不等待聊天开屏、会话或右侧 Tab。
      await waitFor(() => visible(document.querySelector("[role='tree']"))
        && [...document.querySelectorAll<HTMLElement>("[role='treeitem']")].some((element) => element.title === "README.md" && visible(element)), local);
      const file = [...document.querySelectorAll<HTMLElement>("[role='treeitem']")].find((element) => element.title === "README.md");
      if (!file) throw new Error("Preview README.md tree entry is missing");
      file.click();
      await waitFor(() => visible(document.querySelector(".agentspace-editor .monaco-editor"))
        && visible(document.querySelector(".agentspace-tab-active"))
        && document.querySelector(".agentspace-tab-active .agentspace-tab-name")?.textContent === "README.md", local);
      root = document.querySelector(".agentspace-editor")!;
    } else {
      const { useChatRuntimeStore } = await cancellable(import("@origin/features/chat/chatRuntimeStore"), local);
      await waitFor(() => {
        const state = useChatRuntimeStore.getState();
        if (state.skeletonError) throw new Error(state.skeletonError);
        if (Object.keys(state.pageErrors).length) throw new Error("Preview history page failed to load");
        return visible(document.querySelector(".app-layout")) && !document.querySelector(".splash-screen")
          && state.sessionId === options.sessionId && state.initialReady && !state.skeletonLoading
          && (window.__EVOLVE_PREVIEW__?.pendingRequests ?? 0) === 0;
      }, local);
      const selector = `button[data-tab-rail-id="${options.tab}"]`;
      await waitFor(() => {
        const button = document.querySelector<HTMLButtonElement>(selector);
        return visible(button) && !button.disabled;
      }, local);
      const button = document.querySelector<HTMLButtonElement>(selector);
      if (!button || button.disabled) throw new Error(labels.ui.targetUnavailable);
      if (button.getAttribute("aria-current") !== "page") button.click();
      await waitFor(() => button.getAttribute("aria-current") === "page"
        && visible(document.querySelector(`[data-tab-panel="${options.tab}"]`)), local);
      root = document.querySelector(".app-layout")!;
    }
    await cancellable(document.fonts.ready, local);
    await stableLayout(root, local);
    // 重复取得可见资源集合，涵盖激活 Tab 后才挂载的懒资源，隐藏 Tab 不参加准备。
    let previous = new Set<Element>();
    for (;;) {
      const resources = [...document.querySelectorAll("img, audio, video, iframe")].filter(visible);
      for (const resource of resources) {
        if (failedResources.has(resource)) throw new Error(labels.ui.resourceFailed);
        if (resource instanceof HTMLImageElement) {
          if (!resource.currentSrc && !resource.src) continue;
          await cancellable(resource.decode(), local);
          if (!resource.naturalWidth) throw new Error(labels.ui.resourceFailed);
        } else if (resource instanceof HTMLMediaElement) {
          if (resource.preload === "none" || (!resource.currentSrc && !resource.getAttribute("src"))) continue;
          await waitFor(() => {
            if (resource.error) throw new Error(labels.ui.resourceFailed);
            return resource.readyState >= HTMLMediaElement.HAVE_METADATA;
          }, local);
        } else if (resource instanceof HTMLIFrameElement) {
          await waitFor(() => {
            if (failedResources.has(resource)) throw new Error(labels.ui.resourceFailed);
            if (loadedFrames.has(resource)) return true;
            const doc = resource.contentDocument;
            return !!doc && doc.readyState === "complete" && doc.URL !== "about:blank";
          }, local);
        }
      }
      await waitFor(() => (window.__EVOLVE_PREVIEW__?.pendingRequests ?? 0) === 0, local);
      await stableLayout(root, local);
      const current = [...document.querySelectorAll("img, audio, video, iframe")].filter(visible);
      if (current.length === previous.size && current.every((element) => previous.has(element))) break;
      previous = new Set(current);
    }
    local.throwIfAborted();
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener("abort", cancel);
    document.removeEventListener("load", loaded, true);
    document.removeEventListener("error", failed, true);
    controller.abort();
  }
}
