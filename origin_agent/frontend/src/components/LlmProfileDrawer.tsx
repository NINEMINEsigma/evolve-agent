import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";
import { useLlmProfileEditor } from "../hooks/useLlmProfileEditor";
import type { LlmDrawerTab } from "../types/llmProfileUi";
import LlmProfileList from "./llm/LlmProfileList";
import LlmGlobalReferences from "./llm/LlmGlobalReferences";
import LlmProfileDialogs from "./llm/LlmProfileDialogs";
import "../styles/llm-profile.css";

interface LlmProfileDrawerProps {
  open: boolean;
  onClose: () => void;
  llmProfiles: LlmProfileManager;
  width?: number;
  isResizing?: boolean;
  onResizePointerDown?: (event: PointerEvent<HTMLElement>) => void;
  onRegisterCloseGuard?: (guard: (() => void) | null) => void;
}

export default function LlmProfileDrawer({ open, onClose, llmProfiles, width, isResizing, onResizePointerDown, onRegisterCloseGuard }: LlmProfileDrawerProps) {
  const id = useId();
  const [tab, setTab] = useState<LlmDrawerTab>("profiles");
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const editor = useLlmProfileEditor(llmProfiles);
  const root = useRef<HTMLDivElement>(null);
  const editorDialogOpen = editor.pendingLeave || !!editor.deleteTarget || editor.conflictOpen;
  const dialogOpen = editorDialogOpen || referenceDialogOpen;
  const requestClose = useCallback(() => {
    if (!dialogOpen) editor.requestLeave(onClose);
  }, [dialogOpen, editor.requestLeave, onClose]);
  const closeRef = useRef(requestClose);
  closeRef.current = requestClose;
  const dialogRef = useRef(dialogOpen);
  dialogRef.current = dialogOpen;
  useEffect(() => {
    onRegisterCloseGuard?.(requestClose);
    return () => onRegisterCloseGuard?.(null);
  }, [requestClose, onRegisterCloseGuard]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    root.current?.querySelector<HTMLElement>("[role='tab'][aria-selected='true']")?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.defaultPrevented || dialogRef.current) return;
      if (event.key === "Escape") { event.preventDefault(); closeRef.current(); }
      if (event.key !== "Tab") return;
      const items = Array.from(root.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex='0']") ?? [])
        .filter((element) => !element.closest("[hidden]") && element.getClientRects().length > 0);
      const first = items[0], last = items[items.length - 1];
      if (!first) return;
      if (event.shiftKey && (document.activeElement === first || !root.current?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !root.current?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); if (previous?.isConnected) previous.focus(); };
  }, [open]);
  if (!open) return null;
  const editing = editor.state.kind !== "view";

  return <div className="drawer-overlay llm-overlay" onClick={(event) => { if (event.target === event.currentTarget) requestClose(); }}>
    <div ref={root} className="drawer-panel llm-drawer" data-tour="llm-drawer-panel" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`}
      style={width != null ? { width } : undefined}>
      <header className="llm-drawer-heading"><div><span className="llm-eyebrow">模型与用途</span><h2 id={`${id}-title`}>模型配置</h2></div>
        <button className="llm-close" onClick={requestClose} disabled={editor.state.busy || dialogOpen} aria-label="关闭模型配置">×</button>
      </header>
      <div className="llm-tabs" role="tablist" aria-label="模型配置页面">
        {(["profiles", "references"] as const).map((value) => <button key={value} id={`${id}-tab-${value}`} role="tab"
          aria-selected={tab === value} aria-controls={`${id}-panel-${value}`} tabIndex={tab === value ? 0 : -1}
          disabled={dialogOpen} onClick={() => setTab(value)} onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? "profiles" : event.key === "End" ? "references" : value === "profiles" ? "references" : "profiles";
            setTab(next); document.getElementById(`${id}-tab-${next}`)?.focus();
          }}>{value === "profiles" ? "模型配置" : "全局配置引用"}
          {value === "profiles" && editing && <span className="llm-tab-dot" aria-label="正在编辑" />}
        </button>)}
      </div>
      <div id={`${id}-panel-profiles`} className="llm-tab-panel" role="tabpanel" aria-labelledby={`${id}-tab-profiles`} hidden={tab !== "profiles"}>
        <div className="llm-page-scroll"><LlmProfileList manager={llmProfiles} editor={editor} /></div>
        {editing && <footer className="llm-edit-footer"><span>{editor.state.busy ? "正在保存…" : editor.state.saveOutcome === "uncertain" ? "保存结果待确认" : editor.dirty ? "有未保存的修改" : "编辑中"}</span>
          <div className="llm-inline-actions"><button className="llm-button" onClick={editor.cancel} disabled={editor.state.busy}>取消</button>
            <button className="llm-button llm-button--primary" onClick={() => void editor.save()}
              disabled={editor.state.busy || editor.state.externalConflict || editor.state.saveOutcome === "uncertain" || !editor.validation.profile}>
              {editor.state.kind === "create" ? "创建" : "保存"}</button></div>
        </footer>}
      </div>
      <div id={`${id}-panel-references`} className="llm-tab-panel" role="tabpanel" aria-labelledby={`${id}-tab-references`} hidden={tab !== "references"}>
        <div className="llm-page-scroll"><LlmGlobalReferences manager={llmProfiles} onOpenProfiles={() => setTab("profiles")} onDialogOpenChange={setReferenceDialogOpen} /></div>
      </div>
      <LlmProfileDialogs manager={llmProfiles} editor={editor} />
      {onResizePointerDown && <div className={`drawer-resize-handle${isResizing ? " dragging" : ""}`} onPointerDown={onResizePointerDown} />}
    </div>
  </div>;
}
