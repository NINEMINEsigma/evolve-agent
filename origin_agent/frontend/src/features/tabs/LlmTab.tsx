import { useState } from "react";
import { useLlmProfileEditor } from "../../hooks/useLlmProfileEditor";
import type { LlmDrawerTab } from "../../types/llmProfileUi";
import LlmProfileList from "../../components/llm/LlmProfileList";
import LlmGlobalReferences from "../../components/llm/LlmGlobalReferences";
import LlmProfileDialogs from "../../components/llm/LlmProfileDialogs";
import AgentLoopSettingsPage from "../agentLoopSettings/SettingsPage";
import { agentLoopSettingsLabels as labels } from "../agentLoopSettings/labels";
import "../../styles/llm-profile.css";
import type { TabRenderContext } from "./registry";

const pages: readonly { id: LlmDrawerTab; label: string }[] = [
  { id: "profiles", label: labels.profilesTab },
  { id: "references", label: labels.referencesTab },
  { id: "runtime", label: labels.tabTitle },
];

/**
 * 常驻三个二级分页；Profile编辑器生命周期不依赖当前页，草稿跨Tab/会话保留。
 * 运行配置独立于Profile列表读取，只有该页真正激活时才发GET。
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
      <div className="llm-tab-body">
        <header className="llm-drawer-heading">
          <div><span className="llm-eyebrow">{labels.profileEyebrow}</span><h2>{labels.profilesTab}</h2></div>
        </header>
        <div className="llm-tabs" role="tablist" aria-label={labels.tabListLabel}>
          {pages.map((page, index) => (
            <button key={page.id} id={`llm-tab-${page.id}`} role="tab" type="button"
              aria-selected={tab === page.id} aria-controls={`llm-panel-${page.id}`}
              tabIndex={tab === page.id ? 0 : -1} disabled={dialogOpen}
              onClick={() => setTab(page.id)} onKeyDown={(event) => {
                if (dialogOpen || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? pages.length - 1
                  : (index + (event.key === "ArrowLeft" ? -1 : 1) + pages.length) % pages.length;
                const next = pages[nextIndex];
                if (!next) return;
                setTab(next.id);
                document.getElementById(`llm-tab-${next.id}`)?.focus();
              }}>
              {page.label}
              {page.id === "profiles" && editing && <span className="llm-tab-dot" aria-label={labels.editing} />}
            </button>
          ))}
        </div>
        <div id="llm-panel-profiles" className="llm-tab-panel" role="tabpanel" aria-labelledby="llm-tab-profiles" hidden={tab !== "profiles"}>
          <div className="llm-page-scroll"><LlmProfileList manager={manager} editor={editor} /></div>
          {editing && <footer className="llm-edit-footer">
            <span>{editor.state.busy ? labels.saving : editor.state.saveOutcome === "uncertain"
              ? labels.saveUncertain : editor.dirty ? labels.unsaved : labels.editMode}</span>
            <div className="llm-inline-actions">
              <button className="llm-button" onClick={editor.cancel} disabled={editor.state.busy}>{labels.cancel}</button>
              <button className="llm-button llm-button--primary" onClick={() => void editor.save()}
                disabled={editor.state.busy || editor.state.externalConflict || editor.state.saveOutcome === "uncertain" || !editor.validation.profile}>
                {editor.state.kind === "create" ? labels.create : labels.save}
              </button>
            </div>
          </footer>}
        </div>
        <div id="llm-panel-references" className="llm-tab-panel" role="tabpanel" aria-labelledby="llm-tab-references" hidden={tab !== "references"}>
          <div className="llm-page-scroll"><LlmGlobalReferences manager={manager} onOpenProfiles={() => setTab("profiles")} onDialogOpenChange={setReferenceDialogOpen} /></div>
        </div>
        <div id="llm-panel-runtime" className="llm-tab-panel" role="tabpanel" aria-labelledby="llm-tab-runtime" hidden={tab !== "runtime"}>
          <div className="llm-page-scroll"><AgentLoopSettingsPage active={ctx.activeTab === "llm" && tab === "runtime"} /></div>
        </div>
        <LlmProfileDialogs manager={manager} editor={editor} />
      </div>
    </div>
  );
}
