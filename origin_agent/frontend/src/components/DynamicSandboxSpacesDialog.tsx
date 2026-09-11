import { useCallback, useEffect, useState } from "react";
import ModalWindow from "./primitives/ModalWindow";
import type {
  DynamicSandboxSpace,
  DynamicSandboxSpaceWithAvailability,
} from "../types";
import {
  createDynamicSandboxSpace,
  listDynamicSandboxSpaces,
  pickDynamicSandboxDirectory,
  removeDynamicSandboxSpace,
  updateDynamicSandboxSpace,
} from "../services/dynamicSandboxSpacesApi";

interface DynamicSandboxSpacesDialogProps {
  open: boolean;
  onClose: () => void;
}

const EMPTY_SPACE: DynamicSandboxSpace = {
  name: "",
  path: "",
  description: "",
  is_readonly: true,
};

export default function DynamicSandboxSpacesDialog({
  open,
  onClose,
}: DynamicSandboxSpacesDialogProps) {
  const [spaces, setSpaces] = useState<DynamicSandboxSpaceWithAvailability[]>([]);
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<DynamicSandboxSpace>(EMPTY_SPACE);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listDynamicSandboxSpaces();
      setSpaces(data.spaces);
      setError(null);
      setSelectedName((current) => {
        if (current && data.spaces.some((space) => space.name === current)) return current;
        return data.spaces[0]?.name ?? "";
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setEditing(false);
    void refresh();
  }, [open, refresh]);

  const selected = spaces.find((space) => space.name === selectedName) ?? null;

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

  const startNew = useCallback(() => {
    setSelectedName("");
    setDraft({ ...EMPTY_SPACE });
    setEditing(true);
    setError(null);
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
    setError(null);
  }, [selected]);

  const cancelEdit = useCallback(() => {
    setEditing(false);
    setError(null);
    if (!selected && spaces.length > 0) setSelectedName(spaces[0].name);
  }, [selected, spaces]);

  const save = useCallback(async () => {
    if (!draft.name.trim() || !draft.path.trim() || !draft.description.trim()) {
      setError("名称、路径和用途描述不能为空");
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
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [draft, selected, refresh]);

  const remove = useCallback(async () => {
    if (!selected) return;
    if (!window.confirm(`确认删除动态沙盒空间「${selected.name}:」的配置吗？\n目标目录和其中的文件不会被删除。`)) return;
    setBusy(true);
    try {
      await removeDynamicSandboxSpace(selected.name);
      setSelectedName("");
      setEditing(false);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [selected, refresh]);

  const chooseDirectory = useCallback(async () => {
    setBusy(true);
    try {
      const path = await pickDynamicSandboxDirectory();
      if (path !== null) setDraft((current) => ({ ...current, path }));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, []);

  const updateField = <K extends keyof DynamicSandboxSpace>(
    field: K,
    value: DynamicSandboxSpace[K],
  ) => setDraft((current) => ({ ...current, [field]: value }));

  if (!open) return null;

  return (
    <ModalWindow
      title="动态沙盒空间管理"
      onClose={onClose}
      closeOnOverlayClick
      closeOnEsc
      className="dynamic-sandbox-spaces-dialog"
      actions={
        <>
          <button className="modal-btn modal-btn--secondary" onClick={onClose}>关闭</button>
          {editing ? (
            <>
              <button className="modal-btn modal-btn--secondary" onClick={cancelEdit} disabled={busy}>取消</button>
              <button className="modal-btn modal-btn--primary" onClick={() => void save()} disabled={busy}>保存</button>
            </>
          ) : (
            <>
              <button className="modal-btn modal-btn--danger" onClick={() => void remove()} disabled={!selected || busy}>删除配置</button>
              <button className="modal-btn modal-btn--primary" onClick={startNew} disabled={busy}>新增</button>
            </>
          )}
        </>
      }
    >
      {error && (
        <div className="dynamic-sandbox-error">
          <span>{error}</span>
          <button className="modal-btn modal-btn--secondary" onClick={() => void refresh()} disabled={loading}>重试</button>
        </div>
      )}
      {loading && spaces.length === 0 ? (
        <div className="dynamic-sandbox-empty">正在加载动态沙盒空间…</div>
      ) : (
        <div className="dynamic-sandbox-layout">
          <div className="dynamic-sandbox-list">
            {spaces.length === 0 ? (
              <div className="dynamic-sandbox-empty">尚未配置动态沙盒空间</div>
            ) : spaces.map((space) => (
              <button
                key={space.name}
                type="button"
                className={`dynamic-sandbox-list-item${space.name === selectedName ? " active" : ""}`}
                onClick={() => { setSelectedName(space.name); setEditing(false); setError(null); }}
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
    </ModalWindow>
  );
}
