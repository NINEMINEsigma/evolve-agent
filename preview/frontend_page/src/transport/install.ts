import type { PreviewRuntime } from "../types";
import { DEMO_ASSETS } from "../constants";
import { createPreviewFetch } from "./http";
import { PreviewWebSocket } from "./websocket";
import { PreviewEventSource } from "./eventSource";
import { reportPreviewFault } from "../runtime/faults";
import labels from "../content/zh-CN.json";

let installed = false;
export function installPreviewTransport(runtime: PreviewRuntime): () => void {
  if (installed) throw new Error("Preview transport is already installed");
  installed = true;
  const nativeFetch = window.fetch.bind(window);
  const nativeSocket = window.WebSocket;
  const nativeEventSource = window.EventSource;
  const nativeOpen = window.open.bind(window);
  const nativeReplaceState = window.history.replaceState.bind(window.history);
  window.history.replaceState = (data: unknown, unused: string, target?: string | URL | null) => {
    if (target == null) { nativeReplaceState(data, unused, target); return; }
    const url = new URL(target, location.href);
    if (url.origin !== location.origin || (url.pathname !== "/" && !url.pathname.startsWith("/agentspace"))) throw new DOMException("Preview blocks this history target", "SecurityError");
    // 正式会话切换重写URL时保留预览场景；不保留旧session，以免阻止新建会话。
    url.searchParams.set("scene", runtime.options.scene);
    url.searchParams.set("controls", runtime.options.controls ? "1" : "0");
    nativeReplaceState(data, unused, url.href);
  };
  class Socket extends PreviewWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      if (protocols && (typeof protocols === "string" ? protocols.length : protocols.length > 0)) throw new Error("Preview does not use socket protocols");
      super(url, runtime);
    }
  }
  class Source extends PreviewEventSource {
    constructor(url: string | URL, _options?: EventSourceInit) { super(url, runtime); }
  }
  window.fetch = createPreviewFetch(runtime, nativeFetch);
  // 浏览器原生构造器包含通用WebSocket API的重载；此处是明确的预览兼容边界。
  window.WebSocket = Socket as unknown as typeof WebSocket;
  window.EventSource = Source as unknown as typeof EventSource;

  const assets = new Set<string>(Object.values(DEMO_ASSETS));
  function approvedTarget(raw: string | URL | undefined): string | null {
    const url = new URL(raw?.toString() ?? "", location.href);
    if (url.protocol === "blob:") {
      // 所有演示Blob均由当前页面创建；不接受外部复制的Blob URL。
      if (url.origin === location.origin) return url.href;
      return null;
    }
    if (url.origin !== location.origin) return null;
    if (assets.has(url.pathname)) return url.href;
    if (url.pathname === "/" || url.pathname.startsWith("/agentspace/")) {
      const session = url.searchParams.get("session");
      if (session && !runtime.store.seedIds.has(session)) {
        window.alert(labels.ui.temporarySession);
        return null;
      }
      url.searchParams.set("scene", runtime.options.scene);
      if (!session && url.pathname === "/") url.searchParams.set("session", runtime.options.sessionId);
      url.searchParams.set("controls", "0");
      return url.href;
    }
    return null;
  }
  function blocked(raw: string): void {
    let path = "invalid";
    try { path = new URL(raw, location.href).pathname; } catch { /* 不记录潜在敏感查询参数。 */ }
    reportPreviewFault({ code: "navigation", path, message: labels.ui.blockedNavigation });
  }
  window.open = (url?: string | URL, target?: string, features?: string): Window | null => {
    const approved = approvedTarget(url);
    if (!approved) { blocked(url?.toString() ?? ""); return null; }
    return nativeOpen(approved, target, features);
  };
  const onLink = (event: MouseEvent) => {
    const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
    if (!anchor) return;
    if (anchor.hash && anchor.origin === location.origin && anchor.pathname === location.pathname && anchor.search === location.search) return;
    const approved = approvedTarget(anchor.href);
    if (!approved) { event.preventDefault(); event.stopImmediatePropagation(); blocked(anchor.href); return; }
    anchor.href = approved;
  };
  document.addEventListener("click", onLink, true);
  document.addEventListener("auxclick", onLink, true);
  return () => {
    installed = false;
    document.removeEventListener("click", onLink, true);
    document.removeEventListener("auxclick", onLink, true);
    window.fetch = nativeFetch; window.WebSocket = nativeSocket; window.EventSource = nativeEventSource; window.open = nativeOpen;
    window.history.replaceState = nativeReplaceState;
  };
}
