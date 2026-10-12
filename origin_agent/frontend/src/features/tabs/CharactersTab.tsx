import { useState } from "react";
import type { CharacterProfileEntryDto, SubagentSession } from "../../types";
import SubagentAvatar from "../characterAvatars/SubagentAvatar";
import { useCharacterProfiles } from "./useCharacterProfiles";
import type { TabRenderContext } from "./registry";

/** 单个提示词条目：路径标签与正文（null 表示无展开正文）。 */
export interface PromptItem {
  label: string;
  path: string | null;
  content: string | null;
  note: string | null;
}

/**
 * 构建提示词展示条目：首条固定为 profile.md 档案正文（标签含完整路径），
 * 其后按 [profile] 声明顺序展示剩余路径并以游标消费 system_prompts
 * 尾部正文；[profile] 重复声明 profile.md 时不生成冗余占位块。
 *
 * 已知局限（尽力对齐）：resolver 会跳过空白提示词与重复的 profile.md
 * 路径，因此 paths 与正文不保证一一对应；空白文件出现在中间路径时
 * 标签可能错位，内容不丢失。
 */
export function buildPromptItems(entry: CharacterProfileEntryDto): PromptItem[] {
  const items: PromptItem[] = [];
  if (entry.system_prompt.trim()) {
    items.push({
      label: `档案正文（${entry.profile_path}）`,
      path: entry.profile_path,
      content: entry.system_prompt,
      note: null,
    });
  } else {
    items.push({
      label: `档案正文（${entry.profile_path}）`,
      path: entry.profile_path,
      content: null,
      note: "档案正文为空",
    });
  }
  const bodyPrompts = entry.system_prompts.slice(1);
  let cursor = 0;
  for (const promptPath of entry.system_prompt_paths) {
    // A re-declared profile.md path in [profile] is already carried by the
    // first item; skip it instead of rendering a redundant placeholder block.
    if (promptPath === entry.profile_path) continue;
    if (cursor < bodyPrompts.length) {
      items.push({
        label: promptPath,
        path: promptPath,
        content: bodyPrompts[cursor],
        note: null,
      });
      cursor += 1;
    } else {
      items.push({
        label: promptPath,
        path: promptPath,
        content: null,
        note: "空白提示词文件",
      });
    }
  }
  return items;
}

/** 同名角色命中多个子会话时：优先 running，否则取最后一个（最新）。 */
function pickRuntimeSession(
  sessions: Record<string, SubagentSession>,
  name: string,
): SubagentSession | null {
  const matches = Object.values(sessions).filter((s) => s.name === name);
  if (matches.length === 0) return null;
  const running = matches.find((s) => s.status === "running");
  return running ?? matches[matches.length - 1];
}

const RUN_STATUS_TEXT: Record<SubagentSession["status"], string> = {
  running: "运行中",
  completed: "已完成",
  terminated: "已终止",
};

/**
 * Characters tab: read-only directory of all sub-agent character profiles,
 * grouped by type with expandable details. Modification is Agent-mediated —
 * the hint bar tells the user to ask the main agent in chat.
 */
export default function CharactersTab({ ctx }: { ctx: TabRenderContext }) {
  const { profiles, loading, error, refresh } = useCharacterProfiles(
    ctx.activeTab === "characters",
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const groups: Array<{ type: "roleplay" | "task"; title: string; items: CharacterProfileEntryDto[] }> = [
    { type: "roleplay", title: "角色扮演", items: [] },
    { type: "task", title: "任务", items: [] },
  ];
  for (const entry of profiles ?? []) {
    const group = groups.find((g) => g.type === entry.character_type);
    if (group) group.items.push(entry);
  }
  for (const group of groups) {
    group.items.sort((a, b) => a.name.localeCompare(b.name));
  }
  const hasCharacters = groups.some((g) => g.items.length > 0);

  return (
    <div className="characters-tab" data-tour="characters-tab">
      <div className="tab-panel-safe-top" aria-hidden="true" />
      <div className="characters-tab-content">
        <div className="characters-hint">
          此面板为只读。如需创建或修改角色档案，请在聊天中让主Agent操作。
        </div>

        {loading && !profiles && <div className="drawer-empty">正在加载角色档案…</div>}
        {error && (
          <div className="drawer-empty">
            加载失败：{error}
            <button type="button" onClick={() => void refresh()}>重试</button>
          </div>
        )}
        {!loading && !error && !hasCharacters && (
          <div className="drawer-empty">
            尚无角色档案。可在聊天中让主Agent在工作空间 characters/ 目录创建。
          </div>
        )}

        {hasCharacters && groups.filter((g) => g.items.length > 0).map((group) => (
          <div key={group.type} className="characters-group">
            <div className="characters-group-title">
              {group.title} ({group.items.length})
            </div>
            {group.items.map((entry) => {
              const key = `${entry.character_type}/${entry.name}`;
              const isExpanded = expanded.has(key);
              const hasError = entry.error !== null;
              const runtimeSession = pickRuntimeSession(ctx.ws.subagentSessions, entry.name);
              const runStatus = runtimeSession ? RUN_STATUS_TEXT[runtimeSession.status] : "未运行";
              return (
                <div
                  key={key}
                  className={`character-profile-item ${isExpanded ? "expanded" : ""} ${hasError ? "has-error" : ""}`}
                >
                  <button
                    type="button"
                    className="character-profile-head"
                    onClick={() => toggleExpanded(key)}
                    title={entry.name}
                  >
                    <span className="character-profile-avatar">
                      <SubagentAvatar name={entry.name} />
                    </span>
                    <span className="character-profile-name">{entry.name}</span>
                    <span className={`character-profile-badge badge-${entry.character_type}`}>
                      {entry.character_type === "roleplay" ? "扮演" : "任务"}
                    </span>
                    <span className="character-profile-llm">
                      {entry.llm_profile_name || "—"}
                    </span>
                    <span className={`character-status-dot ${entry.profile_available ? "ok" : "error"}`} />
                    <span className="character-run-badge">{runStatus}</span>
                  </button>
                  {isExpanded && (
                    <div className="character-profile-details">
                      {hasError && (
                        <div className="character-profile-error">{entry.error}</div>
                      )}
                      <div className="character-detail-row">
                        <span className="character-detail-label">目录</span>
                        <span className="character-path">{entry.directory_path}</span>
                      </div>
                      <div className="character-detail-row">
                        <span className="character-detail-label">档案</span>
                        <span className="character-path">{entry.profile_path}</span>
                      </div>
                      <div className="character-detail-row">
                        <span className="character-detail-label">简介</span>
                        <span className="character-detail-value">
                          {entry.description || "—"}
                        </span>
                      </div>
                      <div className="character-detail-row">
                        <span className="character-detail-label">LLM Profile</span>
                        <span className="character-detail-value">
                          {entry.llm_profile_name || "—"}
                          {!entry.profile_available && "（不可用）"}
                        </span>
                      </div>
                      <div className="character-prompts">
                        <div className="character-detail-label">系统提示词</div>
                        {buildPromptItems(entry).map((item, index) => (
                          <div key={`${item.path ?? item.label}-${index}`} className="character-prompt-item">
                            <div className="character-prompt-label" title={item.path ?? undefined}>
                              {item.label}
                              {item.note && <span className="character-prompt-note">{item.note}</span>}
                            </div>
                            {item.content !== null && (
                              <pre className="character-prompt-content">{item.content}</pre>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
