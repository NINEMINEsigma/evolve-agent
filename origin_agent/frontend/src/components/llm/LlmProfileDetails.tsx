import { useId } from "react";
import type { ReactNode } from "react";
import type { LlmProfile } from "../../types";
import type { LlmProfileDraft } from "../../types/llmProfileUi";
import type { LlmProfileManager } from "../../hooks/useLlmProfiles";
import type { LlmProfileEditorController } from "../../hooks/useLlmProfileEditor";

interface LlmProfileDetailsProps {
  profile: LlmProfile | null;
  manager: LlmProfileManager;
  editor: LlmProfileEditorController;
}

function ReadValue({ label, children }: { label: string; children: ReactNode }) {
  return <div className="llm-value"><dt>{label}</dt><dd>{children || "未设置"}</dd></div>;
}

export default function LlmProfileDetails({ profile, manager, editor }: LlmProfileDetailsProps) {
  const id = useId();
  const { state, validation } = editor;
  const editing = state.kind !== "view";
  const draft = state.draft;
  const disabled = state.busy || state.saveOutcome === "uncertain";
  const field = (key: keyof LlmProfileDraft, label: string, options?: {
    type?: string; full?: boolean; placeholder?: string; choices?: { value: string; label: string }[];
  }) => {
    if (!draft) return null;
    const value = draft[key] ?? "";
    const error = validation.errors[key];
    return <div className={`llm-field${options?.full ? " llm-field--full" : ""}`} key={key}>
      <label htmlFor={`${id}-${key}`}>{label}</label>
      {options?.choices ? <select id={`${id}-${key}`} value={String(value)} disabled={disabled}
        aria-invalid={!!error} aria-describedby={error ? `${id}-${key}-error` : undefined}
        onChange={(event) => editor.updateField(key, key.endsWith("_profile") ? event.target.value || null : event.target.value)}>
        {options.choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
      </select> : <input id={`${id}-${key}`} type={options?.type ?? "text"} value={String(value)}
        disabled={disabled} placeholder={options?.placeholder} autoComplete={key === "api_key" ? "new-password" : "off"}
        inputMode={key === "temperature" ? "decimal" : key.endsWith("_tokens") ? "numeric" : undefined}
        aria-invalid={!!error} aria-describedby={error ? `${id}-${key}-error` : undefined}
        onChange={(event) => editor.updateField(key, event.target.value)} />}
      {error && <small className="llm-field-error" id={`${id}-${key}-error`}>{error}</small>}
    </div>;
  };
  const profileChoices = [{ value: "", label: "不引用" }, ...manager.profiles.map((item) => ({ value: item.name, label: `${item.name} · ${item.model}` }))];
  const referenceField = (key: "vision_image_profile" | "audio_profile" | "vision_video_profile", label: string) => {
    const value = draft?.[key];
    const choices = value && !manager.profiles.some((item) => item.name === value)
      ? [...profileChoices, { value, label: `${value}（已失效）` }] : profileChoices;
    return field(key, label, { full: true, choices });
  };
  const clients = Array.from(new Set([...manager.availableClients, ...(draft?.llm_client_name ? [draft.llm_client_name] : [])]));
  const efforts = Array.from(new Set(["", "low", "medium", "high", ...(draft?.reasoning_effort ? [draft.reasoning_effort] : [])]));

  return <div className="llm-details">
    <div className="llm-details-heading">
      <div><span className="llm-eyebrow">{editing ? state.kind === "create" ? "新配置" : "编辑配置" : "配置详情"}</span>
        <h3>{editing ? draft?.name || "未命名配置" : profile?.name}</h3>
        {editing && <span className="llm-edit-indicator">{editor.dirty ? "未保存" : "编辑中"}</span>}
      </div>
      {!editing && <div className="llm-inline-actions">
        <button className="llm-button llm-button--primary" onClick={editor.beginEdit} disabled={state.busy}>编辑</button>
        <button className="llm-button" onClick={editor.beginDuplicate} disabled={state.busy}>复制</button>
        <button className="llm-button llm-button--danger" onClick={editor.requestDelete} disabled={state.busy}>删除</button>
      </div>}
    </div>
    {state.error && <div className="llm-message llm-message--error" role="alert">{state.error}</div>}
    {state.saveOutcome === "uncertain" && <div className="llm-message">
      <p>请求可能已经保存成功。确认结果前，草稿保持不变。</p>
      <button className="llm-button" disabled={state.busy} onClick={() => void editor.confirmSaveOutcome()}>刷新确认</button>
    </div>}
    {state.externalConflict && <button className="llm-button" onClick={editor.openConflict} disabled={state.busy}>处理配置冲突</button>}
    {editing && draft ? <>
      <section className="llm-section">
        <h4>连接</h4>
        {manager.clientsError && <div className="llm-message llm-message--error">{manager.clientsError}
          <button className="llm-text-button" onClick={() => void manager.refreshClients().catch(() => {})}>重试</button></div>}
        <div className="llm-field-grid">
          {field("name", "配置名称")}
          {field("llm_client_name", "客户端类型", { choices: clients.map((value) => ({ value, label: value })) })}
          {field("base_url", "API 端点", { full: true, placeholder: "https://api.example.com/v1" })}
          {field("model", "模型名称", { full: true })}
          {field("api_key", "API 密钥", { type: "password", full: true })}
        </div>
      </section>
      <section className="llm-section"><h4>生成参数</h4><div className="llm-field-grid">
        {field("temperature", "采样温度")}
        {field("max_output_tokens", "最大输出 token 数")}
        {field("reasoning_effort", "推理深度", { choices: efforts.map((value) => ({ value, label: value || "不启用" })) })}
        {field("max_context_tokens", "上下文窗口大小")}
      </div></section>
      <section className="llm-section"><h4>多模态分工</h4><div className="llm-field-grid">
        {referenceField("vision_image_profile", "视觉（读图）配置")}
        {referenceField("audio_profile", "听觉配置")}
        {referenceField("vision_video_profile", "视觉（读视频）配置")}
      </div></section>
      <section className="llm-section"><h4>人格</h4>
        <div className="llm-field-grid">{field("soul_file", "灵魂文件名", { full: true, placeholder: "SOUL.md" })}</div>
      </section>
    </> : profile && <>
      <section className="llm-section"><h4>连接</h4><dl className="llm-value-grid">
        <ReadValue label="客户端">{profile.llm_client_name}</ReadValue>
        <ReadValue label="模型">{profile.model}</ReadValue>
        <ReadValue label="API 端点">{profile.base_url}</ReadValue>
        <ReadValue label="API 密钥">{profile.api_key ? "已设置" : "未设置"}</ReadValue>
      </dl></section>
      <section className="llm-section"><h4>生成参数</h4>
        <dl className="llm-value-grid"><ReadValue label="采样温度">{String(profile.temperature)}</ReadValue>
          <ReadValue label="最大输出 token 数">{profile.max_output_tokens.toLocaleString()}</ReadValue>
          <ReadValue label="推理深度">{profile.reasoning_effort || "不启用"}</ReadValue>
          <ReadValue label="上下文窗口大小">{profile.max_context_tokens.toLocaleString()}</ReadValue></dl>
      </section>
      <section className="llm-section"><h4>多模态分工</h4>
        <dl className="llm-value-grid"><ReadValue label="视觉（读图）">{profile.vision_image_profile || "不引用"}</ReadValue>
          <ReadValue label="听觉">{profile.audio_profile || "不引用"}</ReadValue>
          <ReadValue label="视觉（读视频）">{profile.vision_video_profile || "不引用"}</ReadValue></dl>
      </section>
      <section className="llm-section"><h4>人格</h4>
        <dl className="llm-value-grid"><ReadValue label="灵魂文件名">{profile.soul_file}</ReadValue></dl>
      </section>
    </>}
  </div>;
}
