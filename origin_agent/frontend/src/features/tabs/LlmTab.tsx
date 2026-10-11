import { useState } from "react";
import { useLlmProfileEditor } from "../../hooks/useLlmProfileEditor";
import type { LlmDrawerTab } from "../../types/llmProfileUi";
import LlmProfileList from "../../components/llm/LlmProfileList";
import LlmGlobalReferences from "../../components/llm/LlmGlobalReferences";
import LlmProfileDialogs from "../../components/llm/LlmProfileDialogs";
import "../../styles/llm-profile.css";
import type { TabRenderContext } from "./registry";

/**
 * LLM profile tab: de-modalized from the old drawer. No overlay, no focus
 * trap, no close button. The editor state machine (including beforeunload
 * and in-panel requestLeave guards) is fully preserved; drafts survive both
 * tab switches and session switches because the layer stays mounted.
 */
export default function LlmTab({ ctx }: { ctx: TabRenderContext }) {
  const [tab, setTab] = useState<LlmDrawerTab>("profiles");
  const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
  const manager = ctx.ws.llmProfiles;
  const editor = useLlmProfileEditor(manager);
  const editorDialogOpen = editor.pendingLeave || !!editor.deleteTarget || editor.conflictOpen;
  const dialogOpen = editorDialogOpen || referenceDialogOpen;
  const editing = editor.state.kind !== "view";

  return (
    <div className="llm-tab" data-tour="llm-tab">
      <div className="tab-panel-safe-top" aria-hidden="true" />
      <div className="llm-tab-body">
        {manager == null ? (
          <div className="drawer-empty">正在加载模型配置…</div>
        ) : (
          <>
            <header className="llm-drawer-heading"><div><span className="llm-eyebrow">模型与用途</span><h2>模型配置</h2></div></header>
            <div className="llm-tabs" role="tablist" aria-label="模型配置页面">
              {(["profiles", "references"] as const).map((value) => <button key={value} id={`llm-tab-${value}`} role="tab"
                aria-selected={tab === value} aria-controls={`llm-panel-${value}`} tabIndex={tab === value ? 0 : -1}
                disabled={dialogOpen} onClick={() => setTab(value)} onKeyDown={(event) => {
                  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const next = event.key === "Home" ? "profiles" : event.key === "End" ? "references" : value === "profiles" ? "references" : "profiles";
                  setTab(next); document.getElementById(`llm-tab-${next}`)?.focus();
                }}>{value === "profiles" ? "模型配置" : "全局配置引用"}
                {value === "profiles" && editing && <span className="llm-tab-dot" aria-label="正在编辑" />}
              </button>)}
            </div>
            <div id="llm-panel-profiles" className="llm-tab-panel" role="tabpanel" aria-labelledby="llm-tab-profiles" hidden={tab !== "profiles"}>
              <div className="llm-page-scroll"><LlmProfileList manager={manager} editor={editor} /></div>
              {editing && <footer className="llm-edit-footer"><span>{editor.state.busy ? "正在保存…" : editor.state.saveOutcome === "uncertain" ? "保存结果待确认" : editor.dirty ? "有未保存的修改" : "编辑中"}</span>
                <div className="llm-inline-actions"><button className="llm-button" onClick={editor.cancel} disabled={editor.state.busy}>取消</button>
                  <button className="llm-button llm-button--primary" onClick={() => void editor.save()}
                    disabled={editor.state.busy || editor.state.externalConflict || editor.state.saveOutcome === "uncertain" || !editor.validation.profile}>
                    {editor.state.kind === "create" ? "创建" : "保存"}</button></div>
              </footer>}
            </div>
            <div id="llm-panel-references" className="llm-tab-panel" role="tabpanel" aria-labelledby="llm-tab-references" hidden={tab !== "references"}>
              <div className="llm-page-scroll"><LlmGlobalReferences manager={manager} onOpenProfiles={() => setTab("profiles")} onDialogOpenChange={setReferenceDialogOpen} /></div>
            </div>
            <LlmProfileDialogs manager={manager} editor={editor} />
          </>
        )}
      </div>
    </div>
  );
}
