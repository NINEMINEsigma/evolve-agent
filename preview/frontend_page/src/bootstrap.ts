import { parsePreviewOptions } from "./scenes";
import { createPreviewStore } from "./runtime/store";
import { PreviewEvents } from "./runtime/events";
import { installPreviewTransport } from "./transport/install";
import { initializePreviewStorage } from "./adapters/storage";
import { reportPreviewFault, subscribePreviewFaults } from "./runtime/faults";
import { preparePreviewScene } from "./presentation/prepare";
import { installPreviewControls } from "./presentation/controls";
import type { PreviewRuntime } from "./types";
import labels from "./content/zh-CN.json";
import "./presentation/controls.css";

const faultView = document.createElement("aside");
faultView.className = "preview-faults";
faultView.setAttribute("role", "alert");
faultView.hidden = true;
document.body.append(faultView);
subscribePreviewFaults((faults) => {
  faultView.hidden = faults.length === 0;
  faultView.replaceChildren();
  for (const fault of faults) {
    const row = document.createElement("div");
    row.textContent = `${labels.ui.failed} · ${fault.code}: ${fault.message}${fault.path ? ` (${fault.path})` : ""}`;
    faultView.append(row);
  }
});

export async function bootstrapPreview(): Promise<void> {
  const options = parsePreviewOptions(window.location);
  const store = createPreviewStore(options.scene);
  if (!store.sessions.has(options.sessionId)) throw new Error("Scene references an unknown seed session");
  const runtime: PreviewRuntime = {
    options, store, events: new PreviewEvents(), pendingRequests: 0,
    disposed: false, paused: false, blobs: new Set(),
  };
  initializePreviewStorage(options);
  const uninstall = installPreviewTransport(runtime);
  const controller = new AbortController();
  const stopFaultWatch = subscribePreviewFaults((faults) => {
    const latest = faults[faults.length - 1];
    if (latest && !controller.signal.aborted) controller.abort(new Error(`${latest.code}: ${latest.message}`));
  });
  let resolveReady!: () => void;
  let rejectReady!: (reason: unknown) => void;
  const ready = new Promise<void>((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  // 就绪失败通过自己的错误出口显示，避免无人等待API时产生未处理拒绝。
  void ready.catch(() => {});
  const controls = installPreviewControls(runtime, ready);
  const dispose = () => {
    if (runtime.disposed) return;
    runtime.disposed = true;
    controller.abort(); stopFaultWatch(); runtime.events.dispose(); controls.dispose(); uninstall();
    for (const url of runtime.blobs) URL.revokeObjectURL(url);
  };
  window.addEventListener("pagehide", dispose, { once: true });
  try {
    await import("@origin/main");
    await preparePreviewScene(options, controller.signal);
    stopFaultWatch(); resolveReady();
  } catch (error) {
    stopFaultWatch(); rejectReady(error);
    throw error;
  }
}

void bootstrapPreview().catch((error: unknown) => {
  reportPreviewFault({ code: "bootstrap", message: error instanceof Error ? error.message : "Preview initialization failed" });
});
