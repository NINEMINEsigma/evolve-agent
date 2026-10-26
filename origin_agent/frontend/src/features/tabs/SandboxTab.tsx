import { useCallback, useEffect, useState } from "react";
import { LlmConfirmation } from "../../components/llm/LlmProfileDialogs";
import type {
  DynamicSandboxSpace,
} from "../../types";
import {
  createDynamicSandboxSpace,
  pickDynamicSandboxDirectory,
  removeDynamicSandboxSpace,
  updateDynamicSandboxSpace,
} from "../../services/dynamicSandboxSpacesApi";
import "../../styles/llm-profile.css";
import { useTabData } from "./TabDataContext";
import type { TabRenderContext } from "./registry";

/**
 * Sandbox tab: global dynamic sandbox space management, de-modalized from the
 * old command-menu dialog. No overlay, no close button. The list is held by the
 * shared TabDataProvider (lazy-loads on every entry via the activeTab effect);
 * the viewing/editing state machine and REST semantics are preserved verbatim.
 * Drafts survive tab switches and session switches because the layer stays
 * mounted; a beforeunload guard covers page reload while editing.
 */

const EMPTY_SPACE: DynamicSandboxSpace = {
  name: "",
  path: "",
  description: "",
  is_readonly: true,
};

export default function SandboxTab({ ctx }: { ctx: TabRenderContext }) {
  const { spaces, loading, error: listError, refresh: refreshSpaces } = useTabData().sandbox;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<DynamicSandboxSpace>(EMPTY_SPACE);
  const [editing, setEditing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const error = operationError ?? listError;

  const refresh = useCallback(async () => {
    const data = await refreshSpaces();
    if (data === null) return;
    setSelectedName((current) => {
      if (current && data.some((space) => space.name === current)) return current;
      return data[0]?.name ?? "";
    });
  }, [refreshSpaces]);

  // Lazy-load key: every entry into this tab re-fetches the list.
  useEffect(() => {
    if (ctx.activeTab === "sandbox") void refresh();
  }, [ctx.activeTab, refresh]);

  const spacesList = spaces ?? [];
  const selected = spacesList.find((space) => space.name === selectedName) ?? null;

  useEffect(() => {
    if (!editing) {
      setDraft(selected ? {
        name: selected.name,
        path: selected.path,
        description: selected.description,
        is_readonly: selected.is_readonly,
      } : EMPTY_SPACE);
    }
  }, [selected, editing]);

  // Reload guard: only active while editing, aligned with the LlmTab editor.
  useEffect(() => {
    if (!editing) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [editing]);

  const startNew = useCallback(() => {
    setSelectedName("");
    setDraft({ ...EMPTY_SPACE });
    setEditing(true);
    setOperationError(null);
  }, []);

  const startEdit = useCallback(() => {
    if (!selected) return;
    setDraft({
      name: selected.name,
      path: selected.path,
      description: selected.description,
      is_readonly: selected.is_readonly,
    });
    setEditing(true);
    setOperationError(null);
  }, [selected]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
    setOperationError(null);
    if (!selected && spacesList.length > 0) setSelectedName(spacesList[0].name);
  }, [selected, spacesList]);

  const save = useCallback(async () => {
    if (!draft.name.trim() || !draft.path.trim() || !draft.description.trim()) {
      setOperationError("名称、路径和用途描述不能为空");
      return;
    }
    setBusy(true);
    try {
      const next = {
        ...draft,
        name: draft.name.trim(),
        path: draft.path.trim(),
        description: draft.description.trim(),
      };
      if (selected) {
        await updateDynamicSandboxSpace(selected.name, next);
      } else {
        await createDynamicSandboxSpace(next);
      }
      setEditing(false);
      setSelectedName(next.name);
      await refresh();
    } catch (cause) {
      setOperationError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [draft, selected, refresh]);

  const remove = useCallback(async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await removeDynamicSandboxSpace(deleteTarget);
      setSelectedName("");
      setEditing(false);
      setDeleteTarget(null);
      await refresh();
    } catch (cause) {
      setOperationError(cause instanceof Error ? cause.message : String(cause));
      setDeleteTarget(null);
    } finally {
      setBusy(false);
    }
  }, [deleteTarget, refresh]);

  const chooseDirectory = useCallback(async () => {
    setBusy(true);
    try {
      const path = await pickDynamicSandboxDirectory();
      if (path !== null) setDraft((current) => ({ ...current, path }));
      setOperationError(null);
    } catch (cause) {
      setOperationError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, []);

  const updateField = <K extends keyof DynamicSandboxSpace>(
    field: K,
    value: DynamicSandboxSpace[K],
  ) => setDraft((current) => ({ ...current, [field]: value }));

  return (
    <div className="sandbox-tab" data-tour="sandbox-tab">
      <div className="sandbox-tab-body">
        <header className="llm-drawer-heading"><div><span className="llm-eyebrow">全局沙盒</span><h2>动态沙盒空间</h2></div></header>
        <div className="llm-page-scroll">
          {error && (
            <div className="dynamic-sandbox-error">
              <span>{error}</span>
              <button className="modal-btn modal-btn--secondary" onClick={() => void refresh()} disabled={loading}>重试</button>
            </div>
          )}
          {loading && spaces === null ? (
            <div className="dynamic-sandbox-empty">正在加载动态沙盒空间…</div>
          ) : (
            <div className="dynamic-sandbox-layout">
              <div className="dynamic-sandbox-list">
                {spacesList.length === 0 ? (
                  <div className="dynamic-sandbox-empty">尚未配置动态沙盒空间</div>
                ) : spacesList.map((space) => (
                  <button
                    key={space.name}
                    type="button"
                    className={`dynamic-sandbox-list-item${space.name === selectedName ? " active" : ""}`}
                    onClick={() => { setSelectedName(space.name); setEditing(false); setOperationError(null); }}
                    disabled={busy}
                  >
                    <strong>{space.name}:</strong>
                    <span>{space.available ? "目录可用" : "目录不可用"}</span>
                  </button>
                ))}
              </div>
              {(selected || editing) && (
                <div className="dynamic-sandbox-form">
                  <label className="llm-profile-label">命名空间名称</label>
                  <input className="llm-profile-input" value={draft.name} onChange={(e) => updateField("name", e.target.value)} disabled={!editing || !!selected} placeholder="例如 external" />
                  <label className="llm-profile-label">目录路径</label>
                  <div className="dynamic-sandbox-path-row">
                    <input className="llm-profile-input" value={draft.path} onChange={(e) => updateField("path", e.target.value)} disabled={!editing} placeholder="绝对目录路径" />
                    <button className="modal-btn modal-btn--secondary" onClick={() => void chooseDirectory()} disabled={!editing || busy}>选择目录</button>
                  </div>
                  <label className="llm-profile-label">用途描述</label>
                  <textarea className="llm-profile-input dynamic-sandbox-description" value={draft.description} onChange={(e) => updateField("description", e.target.value)} disabled={!editing} placeholder="说明这个空间的用途" />
                  <label className="dynamic-sandbox-readonly">
                    <input type="checkbox" checked={draft.is_readonly} onChange={(e) => updateField("is_readonly", e.target.checked)} disabled={!editing} />
                    仅允许 Sandbox 文件 API 读取
                  </label>
                  {!editing && <button className="modal-btn modal-btn--secondary" onClick={startEdit} disabled={busy}>编辑</button>}
                </div>
              )}
            </div>
          )}
        </div>
        <footer className="llm-edit-footer">
          <span>{busy ? "正在处理…" : editing ? (selected ? "编辑既有空间配置" : "正在新增空间配置") : selected ? `已选中：${selected.name}` : spacesList.length === 0 ? "尚未配置任何空间" : "从左侧列表选择一个空间"}</span>
          <div className="llm-inline-actions">
            {editing ? (
              <>
                <button className="modal-btn modal-btn--secondary" onClick={cancelEdit} disabled={busy}>取消</button>
                <button className="modal-btn modal-btn--primary" onClick={() => void save()} disabled={busy}>保存</button>
              </>
            ) : (
              <>
                <button className="modal-btn modal-btn--danger" onClick={() => selected && setDeleteTarget(selected.name)} disabled={!selected || busy}>删除配置</button>
                <button className="modal-btn modal-btn--primary" onClick={startNew} disabled={busy}>新增</button>
              </>
            )}
          </div>
        </footer>
        {deleteTarget && (
          <LlmConfirmation
            title="删除动态沙盒空间"
            onCancel={() => setDeleteTarget(null)}
            actions={<>
              <button className="modal-btn modal-btn--secondary" data-llm-cancel onClick={() => setDeleteTarget(null)} disabled={busy}>取消</button>
              <button className="modal-btn modal-btn--danger" disabled={busy} onClick={() => void remove()}>{busy ? "删除中…" : "确认删除"}</button>
            </>}
          >
            <p>将删除 <strong>{deleteTarget}:</strong> 的配置。目标目录和其中的文件不会被删除。</p>
          </LlmConfirmation>
        )}
      </div>
    </div>
  );
}
