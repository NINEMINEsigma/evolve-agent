import type { ChatRuntimeState } from "@origin/features/chat/chatRuntimeStore";
import type { PreviewController, PreviewRuntime } from "../types";
import { SCENES } from "../scenes";
import { initializePreviewStorage } from "../adapters/storage";
import { freezePreviewFrame } from "./freeze";
import labels from "../content/zh-CN.json";

export interface PreviewControlApi extends PreviewController {
  readonly pendingRequests: number;
}
declare global { interface Window { __EVOLVE_PREVIEW__?: PreviewControlApi } }

function visible(element: Element): boolean {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && style.visibility === "visible" && style.display !== "none";
}
function hasVisible(selector: string): boolean {
  return [...document.querySelectorAll(selector)].some(visible);
}

export function installPreviewControls(runtime: PreviewRuntime, ready: Promise<void>): { dispose(): void } {
  if (window.__EVOLVE_PREVIEW__) throw new Error("Preview controls are already installed");
  let state: PreviewController["state"] = "preparing";
  let disposed = false;
  let restoreFrame: (() => void) | null = null;
  let rootLease: { element: HTMLElement; inert: boolean } | null = null;
  let readChatState: (() => ChatRuntimeState) | null = null;
  let lastGeometry = "";
  let stableFrames = 0;
  let lastChange = performance.now();
  let watcher = 0;
  const panel = document.createElement("aside");
  panel.className = "preview-controls";
  panel.setAttribute("aria-label", labels.ui.controls);
  const title = document.createElement("h2"); title.textContent = labels.ui.controls;
  const status = document.createElement("p"); status.className = "preview-controls-status";
  status.setAttribute("role", "status"); status.textContent = labels.ui.preparing;
  const scope = document.createElement("p"); scope.className = "preview-controls-scope"; scope.textContent = labels.ui.freezeScope;
  const selectLabel = document.createElement("label"); selectLabel.textContent = labels.ui.scene;
  const select = document.createElement("select"); select.setAttribute("aria-label", labels.ui.scene);
  for (const scene of SCENES) {
    const option = document.createElement("option"); option.value = scene.id; option.textContent = scene.label;
    option.selected = scene.id === runtime.options.scene; select.append(option);
  }
  selectLabel.append(select);
  const actions = document.createElement("div"); actions.className = "preview-controls-actions";
  const notify = (message: string) => { status.textContent = message; };
  const resume = () => {
    restoreFrame?.(); restoreFrame = null;
    if (rootLease) { rootLease.element.inert = rootLease.inert; rootLease = null; }
    runtime.paused = false;
    notify(state === "ready" ? labels.ui.ready : labels.ui[state]);
  };
  const blocked = () => {
    if (disposed || runtime.disposed || state !== "ready" || document.hidden || (!restoreFrame && runtime.pendingRequests !== 0)) return true;
    if (hasVisible(".splash-screen, [role='dialog'], [aria-modal='true'], .modal-overlay, .modal-backdrop, .react-joyride__tooltip, .react-joyride__overlay, [data-onboarding-root] > *")) return true;
    if (!runtime.options.editor) {
      const chat = readChatState?.();
      if (!chat?.initialReady || chat.currentStreamId || chat.liveRows.some((row) => row.streaming)
        || Object.keys(chat.pendingStreamFinishes).length > 0 || Object.keys(chat.pendingMessages).length > 0) return true;
      const session = runtime.store.sessions.get(chat.sessionId);
      if (!session) return true;
      const waiting = !!(session.ask || session.confirm);
      if ((chat.processing || session.activity) && !waiting) return true;
      if (waiting && !hasVisible(".input-morph")) return true;
    }
    return document.getAnimations().some((animation) => {
      const effect = animation.effect;
      const target = effect instanceof KeyframeEffect ? effect.target : null;
      if (target instanceof Element && (!visible(target) || target.closest(".preview-controls"))) return false;
      return animation.playState === "running" && !!effect && effect.getComputedTiming().endTime !== Infinity;
    });
  };
  const freeze = () => {
    if (restoreFrame) return;
    if (blocked() || stableFrames < 2 || performance.now() - lastChange < 120) {
      notify(labels.ui.waitForIdle);
      throw new Error(labels.ui.waitForIdle);
    }
    runtime.paused = true;
    try {
      restoreFrame = freezePreviewFrame();
      const root = document.getElementById("root");
      if (root) { rootLease = { element: root, inert: root.inert }; root.inert = true; }
      notify(labels.ui.frozen);
    } catch (cause) { resume(); throw cause; }
  };
  const reset = () => {
    if (disposed) return;
    resume(); runtime.paused = true;
    runtime.events.dispose();
    for (const url of runtime.blobs) URL.revokeObjectURL(url);
    runtime.blobs.clear();
    initializePreviewStorage(runtime.options);
    const url = new URL(window.location.href);
    url.pathname = runtime.options.editor ? "/agentspace/" : "/";
    url.searchParams.set("scene", runtime.options.scene);
    url.searchParams.set("tab", runtime.options.tab);
    url.searchParams.set("session", runtime.options.sessionId);
    url.searchParams.set("controls", runtime.options.controls ? "1" : "0");
    url.hash = "";
    window.history.replaceState(null, "", url.href);
    window.location.reload();
  };
  const api: PreviewControlApi = Object.freeze({
    ready,
    get state() { return state; },
    get scene() { return runtime.options.scene; },
    get pendingRequests() { return runtime.pendingRequests; },
    reset, freeze, resume,
  });
  window.__EVOLVE_PREVIEW__ = api;
  const action = (label: string, run: () => void) => {
    const button = document.createElement("button"); button.type = "button"; button.textContent = label;
    button.addEventListener("click", () => {
      try { run(); } catch (cause) { notify(cause instanceof Error ? cause.message : labels.ui.failed); }
    });
    actions.append(button);
  };
  action(labels.ui.freeze, freeze); action(labels.ui.resume, resume); action(labels.ui.reset, reset);
  action(labels.ui.hide, () => { panel.hidden = true; });
  panel.append(title, status, selectLabel, actions, scope);
  if (runtime.options.controls) document.body.append(panel);
  select.addEventListener("change", () => {
    resume();
    const url = new URL(window.location.href);
    url.searchParams.set("scene", select.value);
    url.searchParams.delete("session"); url.searchParams.set("tab", "chat");
    window.location.assign(url.href);
  });
  const invalidated = () => { resume(); notify(labels.ui.frameInvalidated); };
  const resumeBlocked = () => notify(labels.ui.mediaResumeBlocked);
  window.addEventListener("preview:frame-invalidated", invalidated);
  window.addEventListener("preview:media-resume-blocked", resumeBlocked);
  const guard = (event: Event) => {
    if (!restoreFrame || (event.target instanceof Element && event.target.closest(".preview-controls"))) return;
    event.preventDefault(); event.stopImmediatePropagation();
  };
  const guardedEvents = ["click", "dblclick", "pointerdown", "pointerover", "pointermove", "mousedown", "mouseover", "mousemove", "keydown", "beforeinput", "wheel", "touchstart", "contextmenu"];
  for (const name of guardedEvents) document.addEventListener(name, guard, { capture: true, passive: false });
  const watch = () => {
    if (disposed) return;
    const geometry = [...document.querySelectorAll(".app-layout, .tab-stage, .input-bar, .input-morph, .sidebar, .agentspace-editor, [data-tab-panel]")]
      .filter(visible).map((element) => {
        const rect = element.getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height].map((value) => Math.round(value * 2)).join(",");
      }).join(";");
    if (geometry !== lastGeometry) { lastGeometry = geometry; stableFrames = 0; lastChange = performance.now(); }
    else stableFrames += 1;
    if (restoreFrame && (blocked() || stableFrames === 0)) invalidated();
    watcher = requestAnimationFrame(watch);
  };
  watcher = requestAnimationFrame(watch);
  void ready.then(async () => {
    if (!runtime.options.editor) {
      // 必须在正式入口完成初始化后才读取正式 store；避免提前求值污染存储基线。
      const module = await import("@origin/features/chat/chatRuntimeStore");
      readChatState = module.useChatRuntimeStore.getState;
    }
    if (!disposed) { state = "ready"; notify(labels.ui.ready); }
  }).catch(() => { if (!disposed) { state = "failed"; notify(labels.ui.failed); } });
  return { dispose() {
    if (disposed) return;
    disposed = true; resume(); cancelAnimationFrame(watcher);
    window.removeEventListener("preview:frame-invalidated", invalidated);
    window.removeEventListener("preview:media-resume-blocked", resumeBlocked);
    for (const name of guardedEvents) document.removeEventListener(name, guard, true);
    panel.remove();
    if (window.__EVOLVE_PREVIEW__ === api) delete window.__EVOLVE_PREVIEW__;
  } };
}
