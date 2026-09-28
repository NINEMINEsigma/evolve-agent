import { useEffect, useId, useMemo, useState } from "react";
import type { LlmProfileManager } from "../../hooks/useLlmProfiles";
import { groupLlmProfiles } from "../../utils/llmProfile";
import { LlmConfirmation } from "./LlmProfileDialogs";

type ReferenceRole = "approval" | "metadata";
interface LlmGlobalReferencesProps {
  manager: LlmProfileManager;
  onOpenProfiles: () => void;
  onDialogOpenChange: (open: boolean) => void;
}

export default function LlmGlobalReferences({ manager, onOpenProfiles, onDialogOpenChange }: LlmGlobalReferencesProps) {
  const id = useId();
  const [confirmRole, setConfirmRole] = useState<ReferenceRole | null>(null);
  const [errors, setErrors] = useState<Partial<Record<ReferenceRole, string>>>({});
  const groups = useMemo(() => groupLlmProfiles(manager.profiles, ""), [manager.profiles]);
  useEffect(() => {
    onDialogOpenChange(confirmRole !== null);
    return () => onDialogOpenChange(false);
  }, [confirmRole, onDialogOpenChange]);
  const assign = async (role: ReferenceRole, name: string | null) => {
    setErrors((previous) => ({ ...previous, [role]: undefined }));
    try {
      if (role === "approval") await manager.setApprovalProfile(name);
      else await manager.setMetadataProfile(name);
      setConfirmRole((current) => current === role && name === null ? null : current);
    } catch (cause) {
      setErrors((previous) => ({ ...previous, [role]: cause instanceof Error ? cause.message : "保存失败" }));
    }
  };
  const cancelConfirm = () => {
    if (confirmRole === "approval" ? manager.approvalBusy : manager.metadataBusy) return;
    setConfirmRole(null);
  };
  const cards: { role: ReferenceRole; title: string; description: string; empty: string }[] = [
    { role: "approval", title: "审批模型", description: "为脱手模式的工具调用执行自动审批。选择在所有会话间共享，不改变各会话的审批模式。", empty: "未配置时，脱手模式无法使用审批模型；YOLO 不受影响。" },
    { role: "metadata", title: "元数据模型", description: "统一生成会话标题、标签与摘要。可选择轻量模型，独立于各会话的对话模型。", empty: "未配置时，使用目标会话已保存的模型配置。" },
  ];
  return <div className="llm-references-page">
    <div className="llm-page-intro"><div className="llm-reference-title"><h3>全局配置引用</h3>
      <button type="button" className="llm-help" data-tooltip="引用已有配置，无需重复填写连接信息。更改后立即保存到服务端。"
        aria-label="全局配置引用说明：引用已有配置，无需重复填写连接信息。更改后立即保存到服务端。">?</button>
    </div></div>
    {manager.profilesError && <div className="llm-message llm-message--error">{manager.profilesError}<button className="llm-text-button" onClick={() => void manager.refreshProfiles().catch(() => {})}>重新加载配置列表</button></div>}
    {cards.map(({ role, title, description, empty }) => {
      const state = role === "approval" ? manager.approvalProfileState : manager.metadataProfileState;
      const status = role === "approval" ? manager.approvalStatus : manager.metadataStatus;
      const busy = role === "approval" ? manager.approvalBusy : manager.metadataBusy;
      const error = errors[role] || (role === "approval" ? manager.approvalError : manager.metadataError);
      const refresh = role === "approval" ? manager.fetchApprovalProfile : manager.fetchMetadataProfile;
      const unknown = !!state.profile_name && !manager.profiles.some((profile) => profile.name === state.profile_name);
      const help = `${description} ${empty} 已明确指定的模型不可用时，不会静默切换到其他模型。`;
      return <section key={role} className="llm-reference-card">
        <div className="llm-reference-title"><h3>{title}</h3><span className="llm-tag">全局</span>
          <button type="button" className="llm-help" data-tooltip={help} aria-label={`${title}说明：${help}`}>?</button>
        </div>
        <label className="llm-field" htmlFor={`${id}-${role}`}>引用配置
          <select id={`${id}-${role}`} value={state.profile_name ?? ""} disabled={busy || status === "loading" || manager.profilesStatus !== "ready"}
            onChange={(event) => { if (event.target.value) void assign(role, event.target.value); }}>
            <option value="" disabled>{status === "loading" ? "正在读取…" : "未配置"}</option>
            {unknown && <option value={state.profile_name!}>{state.profile_name}（目录中不可用）</option>}
            {groups.map((group) => group.baseUrls.map((url) => <optgroup key={JSON.stringify([group.client, url.baseUrl])} label={`${group.client} · ${url.baseUrl || "未设置端点"}`}>
              {url.profiles.map((profile) => <option key={profile.name} value={profile.name}>{profile.name} · {profile.model || "未设置模型"}</option>)}
            </optgroup>))}
          </select>
        </label>
        <div className="llm-reference-footer"><span className={`llm-reference-status${state.profile_name && !state.available ? " llm-reference-status--warning" : ""}`} role="status">
          {busy ? "保存中…" : status === "loading" ? "正在读取引用状态…" : status === "error" ? "读取失败，状态尚未确认" : state.profile_name ? state.available ? `已配置 · ${state.model || state.profile_name}` : "配置不可用" : "未配置"}
        </span><button className="llm-button" disabled={busy || status !== "ready" || !state.profile_name}
          onClick={() => setConfirmRole(role)}>清除</button></div>
        {error && <div className="llm-message llm-message--error" role="alert">{error}<button className="llm-text-button" disabled={busy} onClick={() => {
          setErrors((previous) => ({ ...previous, [role]: undefined })); void refresh().catch(() => {});
        }}>重新读取</button></div>}
      </section>;
    })}
    {manager.profilesStatus === "ready" && manager.profiles.length === 0 && <div className="llm-empty"><p>先创建一个模型配置，再为这些用途建立引用。</p><button className="llm-button" onClick={onOpenProfiles}>前往模型配置</button></div>}
    {confirmRole && <LlmConfirmation title={confirmRole === "approval" ? "清空审批模型引用？" : "清空元数据模型引用？"} onCancel={cancelConfirm} actions={<>
      <button className="modal-btn modal-btn--secondary" data-llm-cancel disabled={manager.approvalBusy || manager.metadataBusy} onClick={cancelConfirm}>取消</button>
      <button className="modal-btn modal-btn--danger" disabled={manager.approvalBusy || manager.metadataBusy} onClick={() => void assign(confirmRole, null)}>确认清空</button>
    </>}><p>{confirmRole === "approval" ? "清空后，脱手模式将无法使用审批模型；各会话审批模式保持不变。" : "清空后，标题、标签和摘要将使用各会话已保存的模型配置。"}</p>
      {errors[confirmRole] && <p className="llm-field-error" role="alert">{errors[confirmRole]}</p>}
    </LlmConfirmation>}
  </div>;
}
