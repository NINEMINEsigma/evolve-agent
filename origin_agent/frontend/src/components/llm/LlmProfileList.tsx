import { useEffect, useId, useMemo, useState } from "react";
import type { LlmProfileManager } from "../../hooks/useLlmProfiles";
import type { LlmProfileEditorController } from "../../hooks/useLlmProfileEditor";
import { groupLlmProfiles } from "../../utils/llmProfile";
import LlmProfileDetails from "./LlmProfileDetails";

interface LlmProfileListProps { manager: LlmProfileManager; editor: LlmProfileEditorController }
const endpointKey = (client: string, url: string) => JSON.stringify([client, url]);

export default function LlmProfileList({ manager, editor }: LlmProfileListProps) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [collapsedClients, setCollapsedClients] = useState<Set<string>>(new Set());
  const [collapsedEndpoints, setCollapsedEndpoints] = useState<Set<string>>(new Set());
  const { state } = editor;
  // 编辑条目按原连接位置固定；外部更新/删除时仍保留草稿可见。
  const source = useMemo(() => state.kind === "edit" && state.baseline
    ? [...manager.profiles.filter((profile) => profile.name !== state.originalName), state.baseline]
    : manager.profiles, [manager.profiles, state.kind, state.baseline, state.originalName]);
  const groups = useMemo(() => {
    const matches = groupLlmProfiles(source, query).flatMap((group) => group.baseUrls.flatMap((url) => url.profiles));
    if (state.kind === "edit" && state.baseline && !matches.some((profile) => profile.name === state.originalName)) matches.push(state.baseline);
    return groupLlmProfiles(matches, "");
  }, [source, query, state.kind, state.baseline, state.originalName]);
  const selectedProfile = source.find((item) => item.name === state.selectedName);
  const selectedClient = selectedProfile?.llm_client_name;
  const selectedEndpoint = selectedProfile?.base_url;
  useEffect(() => {
    if (selectedClient === undefined || selectedEndpoint === undefined) return;
    setCollapsedClients((previous) => { const next = new Set(previous); next.delete(selectedClient); return next; });
    setCollapsedEndpoints((previous) => { const next = new Set(previous); next.delete(endpointKey(selectedClient, selectedEndpoint)); return next; });
  }, [state.selectedName, selectedClient, selectedEndpoint]);
  const toggle = (key: string, client: boolean, containsEditor: boolean) => {
    const perform = () => {
      const setter = client ? setCollapsedClients : setCollapsedEndpoints;
      setter((previous) => { const next = new Set(previous); next.has(key) ? next.delete(key) : next.add(key); return next; });
    };
    if (containsEditor) editor.requestLeave(perform); else perform();
  };

  return <div className="llm-profiles-page">
    <div className="llm-list-toolbar">
      <div className="llm-search"><label className="llm-sr-only" htmlFor={`${id}-search`}>搜索模型配置</label>
        <input id={`${id}-search`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索配置、模型或端点" type="search" />
      </div>
      <button className="llm-button llm-button--primary" onClick={editor.beginCreate} disabled={state.busy || manager.profilesStatus !== "ready"}>新增配置</button>
    </div>
    <div className="llm-list-caption"><span>{manager.profiles.length} 个配置 · 按客户端和端点分组</span>
      <button className="llm-text-button" onClick={() => void manager.refreshProfiles().catch(() => {})} disabled={state.busy}>刷新</button></div>
    {manager.profilesStatus === "loading" && <div className="llm-message" role="status">正在读取模型配置…</div>}
    {(manager.profilesError || manager.profilesWarning) && <div className="llm-message llm-message--error" role="alert">
      {manager.profilesError || manager.profilesWarning}<button className="llm-text-button" onClick={() => void manager.refreshProfiles().catch(() => {})}>重试</button>
      {manager.profilesWarning && <button className="llm-text-button" onClick={manager.dismissProfilesWarning}>关闭提示</button>}
    </div>}
    {editor.notice && <div className="llm-message" role="status">{editor.notice}<button className="llm-text-button" onClick={editor.dismissNotice}>关闭</button></div>}
    {state.kind === "create" && <div className="llm-profile-card llm-profile-card--open"><LlmProfileDetails profile={null} manager={manager} editor={editor} /></div>}
    {manager.profilesStatus === "ready" && groups.length === 0 && state.kind !== "create" && <div className="llm-empty">
      <h3>{manager.profiles.length ? "没有匹配的配置" : "添加第一个模型配置"}</h3>
      <p>{manager.profiles.length ? "尝试搜索配置名称、模型或 API 端点。" : "配置连接信息后，可在顶部栏选择会话待用模型。"}</p>
    </div>}
    {groups.map((group, groupIndex) => {
      const clientOpen = !!query.trim() || !collapsedClients.has(group.client);
      const clientContainsEditor = state.kind === "edit" && state.baseline?.llm_client_name === group.client;
      const clientId = `${id}-client-${groupIndex}`;
      return <section key={group.client} className="llm-client-group">
        <button className="llm-group-heading" aria-expanded={clientOpen} aria-controls={clientId}
          disabled={!!query.trim()} onClick={() => toggle(group.client, true, clientOpen && clientContainsEditor)}>
          <span className={`llm-chevron${clientOpen ? " llm-chevron--open" : ""}`} aria-hidden>›</span>
          <span>{group.client || "未设置客户端"}</span><span className="llm-count">{group.baseUrls.reduce((count, url) => count + url.profiles.length, 0)}</span>
        </button>
        {clientOpen && <div id={clientId} className="llm-group-content">{group.baseUrls.map((url, urlIndex) => {
          const key = endpointKey(group.client, url.baseUrl);
          const open = !!query.trim() || !collapsedEndpoints.has(key);
          const containsEditor = clientContainsEditor && state.baseline?.base_url === url.baseUrl;
          const urlId = `${clientId}-url-${urlIndex}`;
          return <section key={key} className="llm-endpoint-group">
            <button className="llm-endpoint-heading" aria-expanded={open} aria-controls={urlId} disabled={!!query.trim()}
              onClick={() => toggle(key, false, open && containsEditor)}>
              <span className={`llm-chevron${open ? " llm-chevron--open" : ""}`} aria-hidden>›</span>
              <span className="llm-endpoint-name">{url.baseUrl || "未设置端点"}</span><span className="llm-count">{url.profiles.length}</span>
            </button>
            {open && <div id={urlId} className="llm-profile-stack">{url.profiles.map((profile, profileIndex) => {
              const selected = state.selectedName === profile.name;
              const detailId = `${urlId}-profile-${profileIndex}`;
              return <article key={profile.name} className={`llm-profile-card${selected ? " llm-profile-card--open" : ""}`}>
                <button className="llm-profile-heading" aria-expanded={selected} aria-controls={detailId}
                  onClick={() => editor.selectProfile(profile.name)} disabled={state.busy}>
                  <span className="llm-profile-identity"><strong>{profile.name}</strong><span>{profile.model || "未设置模型"}</span></span>
                  <span className="llm-tags">
                    {state.kind === "edit" && selected && <span>正在编辑</span>}
                    {manager.approvalProfileName === profile.name && <span>审批</span>}
                    {manager.metadataProfileName === profile.name && <span>元数据</span>}
                  </span>
                  <span className={`llm-chevron${selected ? " llm-chevron--open" : ""}`} aria-hidden>›</span>
                </button>
                {selected && <div id={detailId}><LlmProfileDetails profile={profile} manager={manager} editor={editor} /></div>}
              </article>;
            })}</div>}
          </section>;
        })}</div>}
      </section>;
    })}
  </div>;
}
