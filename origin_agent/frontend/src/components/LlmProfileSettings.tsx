import { useCallback, useEffect, useState } from "react";
import ModalWindow from "./primitives/ModalWindow";
import type { LlmProfile } from "../types";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";

interface LlmProfileSettingsProps {
  llmProfiles: LlmProfileManager;
  onClose: () => void;
}

const EMPTY_PROFILE: LlmProfile = {
  name: "",
  llm_client_name: "openai_client",
  base_url: "",
  model: "",
  api_key: "",
  temperature: 0.7,
  max_output_tokens: 4096,
  reasoning_effort: "",
  max_context_tokens: 128000,
};

function generateDuplicateName(sourceName: string, existingNames: string[]): string {
  let n = 1;
  let candidate = `${sourceName}${n}`;
  while (existingNames.includes(candidate)) {
    n++;
    candidate = `${sourceName}${n}`;
  }
  return candidate;
}

export default function LlmProfileSettings({
  llmProfiles,
  onClose,
}: LlmProfileSettingsProps) {
  const {
    profiles,
    activeProfileName,
    addProfile,
    updateProfile,
    deleteProfile,
    availableClients,
  } = llmProfiles;

  const [selectedName, setSelectedName] = useState<string>(activeProfileName);
  const [draft, setDraft] = useState<LlmProfile>(EMPTY_PROFILE);
  const [isEditing, setIsEditing] = useState(false);
  const [isNew, setIsNew] = useState(false);

  const selectedProfile = profiles.find((p) => p.name === selectedName) || null;
  const isDefault = selectedName === "default";

  useEffect(() => {
    if (selectedProfile && !isNew) {
      setDraft({ ...selectedProfile });
      setIsEditing(false);
    }
  }, [selectedName, selectedProfile, isNew]);

  const handleSelect = useCallback((name: string) => {
    setSelectedName(name);
    setIsNew(false);
    setIsEditing(false);
  }, []);

  const handleNew = useCallback(() => {
    setIsNew(true);
    setIsEditing(true);
    setDraft({ ...EMPTY_PROFILE, name: "" });
    setSelectedName("");
  }, []);

  const handleEdit = useCallback(() => {
    if (isDefault) return;
    setIsEditing(true);
  }, [isDefault]);

  const handleSave = useCallback(() => {
    if (!draft.name.trim()) return;
    if (isNew) {
      addProfile({ ...draft, name: draft.name.trim() });
    } else {
      updateProfile(selectedName, { ...draft, name: draft.name.trim() });
    }
    setIsEditing(false);
    setIsNew(false);
    setSelectedName(draft.name.trim());
  }, [draft, isNew, selectedName, addProfile, updateProfile]);

  const handleDelete = useCallback(() => {
    if (isDefault) return;
    deleteProfile(selectedName);
    setSelectedName("default");
    setIsEditing(false);
    setIsNew(false);
  }, [isDefault, selectedName, deleteProfile]);

  const handleDuplicate = useCallback(() => {
    if (!selectedProfile) return;
    const existingNames = profiles.map((p) => p.name);
    const newName = generateDuplicateName(selectedProfile.name, existingNames);
    setIsNew(true);
    setIsEditing(true);
    setDraft({ ...selectedProfile, name: newName });
    setSelectedName("");
  }, [selectedProfile, profiles]);

  const handleCancel = useCallback(() => {
    if (isNew) {
      setSelectedName(activeProfileName);
      setIsNew(false);
    } else if (selectedProfile) {
      setDraft({ ...selectedProfile });
    }
    setIsEditing(false);
  }, [isNew, selectedProfile, activeProfileName]);

  const updateField = useCallback(
    <K extends keyof LlmProfile>(field: K, value: LlmProfile[K]) => {
      setDraft((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const nameExists = isNew && profiles.some(
    (p) => p.name === draft.name.trim(),
  );

  return (
    <ModalWindow
      title="模型配置"
      onClose={onClose}
      closeOnEsc
      className="llm-profile-settings"
      actions={
        <>
          {isEditing ? (
            <>
              <button className="modal-btn modal-btn--secondary" onClick={handleCancel}>
                取消
              </button>
              <button
                className="modal-btn modal-btn--primary"
                onClick={handleSave}
                disabled={!draft.name.trim() || nameExists}
              >
                {isNew ? "创建" : "保存"}
              </button>
            </>
          ) : (
            <>
              {!isDefault && (
                <>
                  <button className="modal-btn modal-btn--danger" onClick={handleDelete}>
                    删除
                  </button>
                  <button className="modal-btn modal-btn--secondary" onClick={handleEdit}>
                    编辑
                  </button>
                </>
              )}
              <button className="modal-btn modal-btn--secondary" onClick={handleDuplicate}>
                复制
              </button>
              <button className="modal-btn modal-btn--secondary" onClick={onClose}>
                关闭
              </button>
            </>
          )}
        </>
      }
    >
      <div className="llm-profile-layout">
        {/* 左侧：配置列表 */}
        <div className="llm-profile-list">
          {profiles.map((p) => (
            <div
              key={p.name}
              className={`llm-profile-item${p.name === selectedName ? " active" : ""}${p.name === activeProfileName ? " current" : ""}`}
              onClick={() => handleSelect(p.name)}
            >
              <span className="llm-profile-item-name">
                {p.name === "default" ? "默认配置" : p.name}
              </span>
              <span className="llm-profile-item-model">{p.model}</span>
            </div>
          ))}
          <button className="modal-btn modal-btn--secondary llm-profile-add-btn" onClick={handleNew}>
            + 新增配置
          </button>
        </div>

        {/* 右侧：编辑表单 */}
        <div className="llm-profile-form">
          {selectedProfile || isNew ? (
            <>
              <div className="llm-profile-section">
                <div className="llm-profile-section-title">连接</div>

                <label className="llm-profile-label">配置名称</label>
                <input
                  className="llm-profile-input"
                  type="text"
                  value={draft.name}
                  onChange={(e) => updateField("name", e.target.value)}
                  disabled={!isEditing}
                  placeholder={isDefault ? "默认配置" : "输入配置名称"}
                />
                {nameExists && (
                  <div className="llm-profile-error">配置名称已存在</div>
                )}

                <label className="llm-profile-label">客户端类型</label>
                <select
                  className="llm-profile-input"
                  value={draft.llm_client_name}
                  onChange={(e) => updateField("llm_client_name", e.target.value)}
                  disabled={!isEditing}
                >
                  {availableClients.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>

                <label className="llm-profile-label">API 端点</label>
                <input
                  className="llm-profile-input"
                  type="text"
                  value={draft.base_url}
                  onChange={(e) => updateField("base_url", e.target.value)}
                  disabled={!isEditing}
                  placeholder="https://api.example.com/v1"
                />

                <label className="llm-profile-label">模型名称</label>
                <input
                  className="llm-profile-input"
                  type="text"
                  value={draft.model}
                  onChange={(e) => updateField("model", e.target.value)}
                  disabled={!isEditing}
                  placeholder="gpt-4o"
                />

                <label className="llm-profile-label">API 密钥</label>
                <input
                  className="llm-profile-input"
                  type="password"
                  value={draft.api_key}
                  onChange={(e) => updateField("api_key", e.target.value)}
                  disabled={!isEditing}
                  placeholder={isDefault ? "（启动时配置）" : "sk-..."}
                />
              </div>

              <div className="llm-profile-section">
                <div className="llm-profile-section-title">参数</div>

                <label className="llm-profile-label">采样温度</label>
                <input
                  className="llm-profile-input"
                  type="number"
                  step={0.05}
                  min={0}
                  max={2}
                  value={draft.temperature}
                  onChange={(e) => updateField("temperature", parseFloat(e.target.value) || 0)}
                  disabled={!isEditing}
                />

                <label className="llm-profile-label">最大输出 token 数</label>
                <input
                  className="llm-profile-input"
                  type="number"
                  value={draft.max_output_tokens}
                  onChange={(e) => updateField("max_output_tokens", parseInt(e.target.value) || 0)}
                  disabled={!isEditing}
                />

                <label className="llm-profile-label">推理深度</label>
                <select
                  className="llm-profile-input"
                  value={draft.reasoning_effort}
                  onChange={(e) => updateField("reasoning_effort", e.target.value)}
                  disabled={!isEditing}
                >
                  <option value="">不启用</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>

                <label className="llm-profile-label">上下文窗口大小</label>
                <input
                  className="llm-profile-input"
                  type="number"
                  value={draft.max_context_tokens}
                  onChange={(e) => updateField("max_context_tokens", parseInt(e.target.value) || 0)}
                  disabled={!isEditing}
                />
              </div>
            </>
          ) : (
            <div className="llm-profile-empty">选择一个配置项或点击"新增配置"</div>
          )}
        </div>
      </div>
    </ModalWindow>
  );
}