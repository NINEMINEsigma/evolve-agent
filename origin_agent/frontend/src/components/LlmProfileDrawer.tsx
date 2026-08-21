import { useCallback, useEffect, useMemo, useState } from "react";
import type { LlmProfile } from "../types";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";

interface LlmProfileDrawerProps {
  open: boolean;
  onClose: () => void;
  llmProfiles: LlmProfileManager;
  width?: number;
  isResizing?: boolean;
  onResizePointerDown?: (e: React.PointerEvent<HTMLElement>) => void;
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

/** 三级树数据结构: 客户端类型 → base_url → 配置项列表 */
interface LlmTreeNode {
  client: string;
  baseUrls: {
    baseUrl: string;
    profiles: LlmProfile[];
  }[];
}

export default function LlmProfileDrawer({
  open,
  onClose,
  llmProfiles,
  width,
  isResizing,
  onResizePointerDown,
}: LlmProfileDrawerProps) {
  const {
    profiles,
    activeProfileName,
    addProfile,
    updateProfile,
    deleteProfile,
    availableClients,
    setActiveProfile,
    error: profileError,
  } = llmProfiles;

  const [selectedName, setSelectedName] = useState<string>(activeProfileName);
  const [draft, setDraft] = useState<LlmProfile>(EMPTY_PROFILE);
  const [isEditing, setIsEditing] = useState(false);
  const [isNew, setIsNew] = useState(false);
  // 树展开状态: Set<string>，存储 "client" 和 "client\x00baseUrl" 形式的键
  // 不持久化,每次打开抽屉时通过 useEffect 自动展开 active profile 路径
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const selectedProfile = profiles.find((p) => p.name === selectedName) || null;
  const nameExists = isNew && profiles.some((p) => p.name === draft.name.trim());

  // 三级树: 按 llm_client_name → base_url 分组
  const tree = useMemo<LlmTreeNode[]>(() => {
    const map = new Map<string, Map<string, LlmProfile[]>>();
    for (const p of profiles) {
      if (!map.has(p.llm_client_name)) map.set(p.llm_client_name, new Map());
      const clientMap = map.get(p.llm_client_name)!;
      if (!clientMap.has(p.base_url)) clientMap.set(p.base_url, []);
      clientMap.get(p.base_url)!.push(p);
    }
    return Array.from(map.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([client, clientMap]) => ({
        client,
        baseUrls: Array.from(clientMap.entries())
          .sort((a, b) => a[0].localeCompare(b[0]))
          .map(([baseUrl, profs]) => ({ baseUrl, profiles: profs })),
      }));
  }, [profiles]);

  // 展开指定 profile 所在路径
  const expandPath = useCallback((profile: LlmProfile) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      next.add(profile.llm_client_name);
      next.add(`${profile.llm_client_name}\x00${profile.base_url}`);
      return next;
    });
  }, []);

  // 抽屉打开时自动展开 active profile 路径
  useEffect(() => {
    if (!open) return;
    const active = profiles.find((p) => p.name === activeProfileName);
    if (active) expandPath(active);
  }, [open, activeProfileName, profiles, expandPath]);

  // ESC 关闭支持
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 选中配置变化时同步 draft
  useEffect(() => {
    if (selectedProfile && !isNew) {
      setDraft({ ...selectedProfile });
      setIsEditing(false);
    }
  }, [selectedName, selectedProfile, isNew]);

  const toggleExpand = useCallback((key: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);

  const handleSelect = useCallback((name: string) => {
    setSelectedName(name);
    setIsNew(false);
    setIsEditing(false);
  }, []);

  const handleNew = useCallback(() => {
    // 若当前选中的是真实 profile,预填其 client 和 base_url
    const prefill = selectedProfile
      ? { ...EMPTY_PROFILE, llm_client_name: selectedProfile.llm_client_name, base_url: selectedProfile.base_url }
      : { ...EMPTY_PROFILE };
    setIsNew(true);
    setIsEditing(true);
    setDraft(prefill);
    setSelectedName("");
  }, [selectedProfile]);

  const handleEdit = useCallback(() => {
    setIsEditing(true);
  }, []);

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
    // 保存后自动展开新路径以保持可见
    expandPath(draft);
  }, [draft, isNew, selectedName, addProfile, updateProfile, expandPath]);

  const handleDelete = useCallback(() => {
    deleteProfile(selectedName);
    setIsEditing(false);
    setIsNew(false);
  }, [selectedName, deleteProfile]);

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

  const handleSetActive = useCallback((name: string) => {
    setActiveProfile(name);
  }, [setActiveProfile]);

  const updateField = useCallback(
    <K extends keyof LlmProfile>(field: K, value: LlmProfile[K]) => {
      setDraft((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  if (!open) return null;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div
        className="drawer-panel llm-drawer"
        style={width != null ? { width } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="drawer-header">
          <span className="drawer-title">模型配置</span>
          <div className="llm-drawer-header-actions">
            <button className="drawer-header-btn" onClick={handleNew}>+ 新增</button>
            <button className="drawer-close" onClick={onClose}>✕</button>
          </div>
        </div>
        {profileError && (
          <div className="llm-profile-error-banner">{profileError}</div>
        )}

        {/* Body: 左右分栏 */}
        <div className="llm-drawer-body">
          {/* 左栏: 三级树 */}
          <div className="llm-tree">
            {tree.map((clientNode) => (
              <div key={clientNode.client} className="llm-tree-client">
                {/* 一级: 客户端类型 */}
                <div
                  className="llm-tree-node-header"
                  onClick={() => toggleExpand(clientNode.client)}
                >
                  <span className={`llm-tree-arrow ${expandedNodes.has(clientNode.client) ? "expanded" : ""}`}>▶</span>
                  <span className="llm-tree-label">{clientNode.client}</span>
                  <span className="llm-tree-count">{clientNode.baseUrls.reduce((n, b) => n + b.profiles.length, 0)}</span>
                </div>
                {expandedNodes.has(clientNode.client) && clientNode.baseUrls.map((urlNode) => (
                  <div key={urlNode.baseUrl} className="llm-tree-baseurl">
                    {/* 二级: base_url */}
                    <div
                      className="llm-tree-node-header llm-tree-node-header-sub"
                      onClick={() => toggleExpand(`${clientNode.client}\x00${urlNode.baseUrl}`)}
                    >
                      <span className={`llm-tree-arrow ${expandedNodes.has(`${clientNode.client}\x00${urlNode.baseUrl}`) ? "expanded" : ""}`}>▶</span>
                      <span className="llm-tree-label llm-tree-label-mono">{urlNode.baseUrl || "(空)"}</span>
                      <span className="llm-tree-count">{urlNode.profiles.length}</span>
                    </div>
                    {expandedNodes.has(`${clientNode.client}\x00${urlNode.baseUrl}`) && urlNode.profiles.map((p) => (
                      /* 三级: 配置项叶子 */
                      <div
                        key={p.name}
                        className={`llm-tree-leaf${p.name === selectedName ? " active" : ""}${p.name === activeProfileName ? " current" : ""}`}
                        onClick={() => handleSelect(p.name)}
                      >
                        <span className="llm-tree-leaf-name">
                          {p.name}
                        </span>
                        <span className="llm-tree-leaf-model">{p.model}</span>
                        {/* "设为当前" 开关 */}
                        <button
                          className={`llm-tree-active-toggle${p.name === activeProfileName ? " on" : ""}`}
                          onClick={(e) => { e.stopPropagation(); handleSetActive(p.name); }}
                          data-tooltip={p.name === activeProfileName ? "当前使用中" : "设为当前"}
                          disabled={p.name === activeProfileName}
                        >
                          {p.name === activeProfileName ? "●" : "○"}
                        </button>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* 右栏: 编辑表单 */}
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
                    placeholder="输入配置名称"
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
                    placeholder="sk-..."
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

                {/* 操作按钮区 */}
                <div className="llm-profile-form-actions">
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
                      <button className="modal-btn modal-btn--danger" onClick={handleDelete}>
                        删除
                      </button>
                      <button className="modal-btn modal-btn--secondary" onClick={handleEdit}>
                        编辑
                      </button>
                      <button className="modal-btn modal-btn--secondary" onClick={handleDuplicate}>
                        复制
                      </button>
                    </>
                  )}
                </div>
              </>
            ) : (
              <div className="llm-profile-empty">
                {profiles.length === 0
                  ? "尚无模型配置，请点击「新增」创建第一个配置"
                  : "选择一个配置项或点击\"新增\""}
              </div>
            )}
          </div>
        </div>

        {/* 拖拽手柄 */}
        {onResizePointerDown && (
          <div
            className={`drawer-resize-handle ${isResizing ? "dragging" : ""}`}
            onPointerDown={onResizePointerDown}
          />
        )}
      </div>
    </div>
  );
}