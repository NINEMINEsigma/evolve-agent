import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import ModalWindow from "../primitives/ModalWindow";
import type { LlmProfileManager } from "../../hooks/useLlmProfiles";
import type { LlmProfileEditorController } from "../../hooks/useLlmProfileEditor";

/** 只在本抽屉内复用的确认壳；不改变应用其他 ModalWindow 的行为。 */
export function LlmConfirmation({ title, children, actions, onCancel }: {
  title: string; children: ReactNode; actions: ReactNode; onCancel: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = root.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>("button:not(:disabled), select:not(:disabled), input:not(:disabled), [tabindex='0']") ?? []);
    (dialog?.querySelector<HTMLElement>("[data-llm-cancel]") ?? focusable()[0])?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancelRef.current(); }
      if (event.key !== "Tab") return;
      const items = focusable();
      const first = items[0], last = items[items.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("keydown", key, true); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div ref={root} className="llm-confirmation"><ModalWindow title={title} actions={actions} className="llm-confirmation-window">{children}</ModalWindow></div>;
}

export default function LlmProfileDialogs({ manager, editor }: {
  manager: LlmProfileManager; editor: LlmProfileEditorController;
}) {
  const { state, deleteTarget } = editor;
  const remaining = manager.profiles.filter((profile) => profile.name !== deleteTarget);
  const defaultReplacement = remaining.some((profile) => profile.name === manager.activeProfileName)
    ? manager.activeProfileName : remaining[0]?.name ?? "";
  const [replacement, setReplacement] = useState(defaultReplacement);
  useEffect(() => { setReplacement(defaultReplacement); }, [deleteTarget, defaultReplacement]);
  const replacementValid = !replacement || remaining.some((profile) => profile.name === replacement);
  if (editor.pendingLeave) return <LlmConfirmation title="保存当前修改？" onCancel={() => void editor.resolveLeave("cancel")} actions={<>
    <button className="modal-btn modal-btn--secondary" data-llm-cancel disabled={state.busy} onClick={() => void editor.resolveLeave("cancel")}>继续编辑</button>
    <button className="modal-btn modal-btn--danger" disabled={state.busy} onClick={() => void editor.resolveLeave("discard")}>放弃修改</button>
    <button className="modal-btn modal-btn--primary" disabled={state.busy || state.externalConflict || state.saveOutcome === "uncertain" || !editor.validation.profile}
      onClick={() => void editor.resolveLeave("save")}>{state.busy ? "保存中…" : "保存并继续"}</button>
  </>}><p>当前配置有未保存的修改。分页切换会保留草稿，离开配置前请选择如何处理。</p>
    {state.saveOutcome === "uncertain" && <p>上次保存结果尚未确认，请先继续编辑并点击“刷新确认”。</p>}
    {state.error && <p className="llm-field-error" role="alert">{state.error}</p>}
  </LlmConfirmation>;
  if (deleteTarget) return <LlmConfirmation title="删除模型配置" onCancel={editor.cancelDelete} actions={<>
    <button className="modal-btn modal-btn--secondary" data-llm-cancel onClick={editor.cancelDelete} disabled={state.busy}>取消</button>
    <button className="modal-btn modal-btn--danger" disabled={state.busy || !replacementValid}
      onClick={() => void editor.confirmDelete(replacement || null)}>{state.busy ? "删除中…" : "确认删除"}</button>
  </>}><p>将删除 <strong>{deleteTarget}</strong>。引用该配置的会话名称指针会改为下方选择；正在处理的回复不在中途切换。</p>
    <p>若它是审批或元数据模型，对应全局引用将被清空，各会话审批模式保持不变。</p>
    <label className="llm-field">替换配置<select value={replacement} onChange={(event) => setReplacement(event.target.value)} disabled={state.busy}>
      <option value="">无配置</option>{remaining.map((profile) => <option key={profile.name} value={profile.name}>{profile.name}</option>)}
    </select></label>
    {state.error && <p className="llm-field-error" role="alert">{state.error}</p>}
  </LlmConfirmation>;
  if (editor.conflictOpen) return <LlmConfirmation title="处理配置冲突" onCancel={editor.closeConflict} actions={<>
    <button className="modal-btn modal-btn--secondary" data-llm-cancel onClick={editor.closeConflict}>保留草稿</button>
    <button className="modal-btn modal-btn--danger" onClick={editor.reloadExternal}>放弃并重新载入</button>
    <button className="modal-btn modal-btn--primary" onClick={editor.saveAsNew}>另存为新配置</button>
  </>}><p>服务端配置已变更或删除。当前草稿不会自动覆盖其他修改；可以放弃草稿，或使用新的名称继续保存。</p></LlmConfirmation>;
  return null;
}
