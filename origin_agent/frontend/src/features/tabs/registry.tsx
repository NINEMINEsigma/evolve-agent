import type { ReactNode } from "react";
import type { WebSocketState } from "../../hooks/useWebSocket";
import type { useSessionSite } from "../../hooks/useSessionSite";
import type { SessionStageState } from "../../hooks/useSessionStage";
import type { SessionChatStyleState } from "../../hooks/useSessionChatStyle";
import ResourcesTab from "./ResourcesTab";
import SubagentsTab from "./SubagentsTab";
import CharactersTab from "./CharactersTab";
import SiteTab from "./SiteTab";
import LlmTab from "./LlmTab";
import ChatTab from "./ChatTab";
import SandboxTab from "./SandboxTab";
import VariablesTab from "./VariablesTab";
import MediaInputTab from "./MediaInputTab";
import { mediaInputLabels } from "../sessionMedia/labels";
import type { TabPreviewInput, TabPreviewModel } from "./tabPreviewTypes";
import {
  selectChatPreview, selectCharactersPreview, selectLlmPreview, selectMediaPreview,
  selectResourcesPreview, selectSandboxPreview, selectSitePreview, selectSubagentsPreview,
  selectVariablesPreview,
} from "./tabPreviewSelectors";

/** Tab id union. Adding a future tab = one registry entry + one enabled derivation in useTabSystem. */
export type TabId = "chat" | "resources" | "media" | "variables" | "subagents" | "characters" | "site" | "llm" | "sandbox";

/** Shared render context handed to every tab content layer. */
export interface TabRenderContext {
  ws: WebSocketState;
  activeTab: TabId;
  siteStatus: ReturnType<typeof useSessionSite>;
  sessionId: string;
  // chat tab
  targetSessions: string[];
  setTargetSessions: React.Dispatch<React.SetStateAction<string[]>>;
  visibleCharacters: string[];
  responseCharacters: string[];
  onToggleAgentState: (agentName: string) => void;
  onToggleMessageVisibility: (messageId: string, agentName: string) => void;
  setLightboxSrc: (src: string | null) => void;
  currentSessionArchived: boolean;
  clipboardCollapsed: boolean;
  onToggleClipboardCollapse: () => void;
  stageState: SessionStageState;
  chatStyleCssText: string | null;
  chatStyleStatus: SessionChatStyleState["status"];
  chatStyleReloadKey: number;
  // subagents tab
  activeSubagentId: string | null;
  setActiveSubagentId: (id: string) => void;
}

export interface TabDefinition {
  id: TabId;
  title: string;
  icon: ReactNode;
  render: (ctx: TabRenderContext) => ReactNode;
  /** 可选只读摘要选择器；缺失时该 Tab 摘要不可用，不影响编译。 */
  preview?: (input: TabPreviewInput) => TabPreviewModel;
}

const chatIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const resourcesIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </svg>
);

const mediaIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="m10 8 6 4-6 4z" />
  </svg>
);

const variablesIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 4H5v16h3M16 4h3v16h-3" />
    <path d="m9 9 6 6m0-6-6 6" />
  </svg>
);

const subagentsIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);

const charactersIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="12" cy="10" r="3" />
    <path d="M7.5 17a4.5 4.5 0 0 1 9 0" />
  </svg>
);

const siteIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <line x1="2" y1="9" x2="22" y2="9" />
    <circle cx="5" cy="6.5" r="0.5" fill="currentColor" />
    <circle cx="7.5" cy="6.5" r="0.5" fill="currentColor" />
  </svg>
);

const llmIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 21v-7" />
    <path d="M4 10V3" />
    <path d="M12 21v-9" />
    <path d="M12 8V3" />
    <path d="M20 21v-5" />
    <path d="M20 12V3" />
    <line x1="2" y1="14" x2="6" y2="14" />
    <line x1="10" y1="8" x2="14" y2="8" />
    <line x1="18" y1="16" x2="22" y2="16" />
  </svg>
);

const sandboxIcon = (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" />
    <path d="M12 12l8-4.5" />
    <path d="M12 12v9" />
    <path d="M12 12L4 7.5" />
  </svg>
);

/** Declarative tab registry. The rail and the stage both render from this list. */
export const TAB_REGISTRY: readonly TabDefinition[] = [
  { id: "chat", title: "聊天", icon: chatIcon, render: (ctx) => <ChatTab ctx={ctx} />, preview: selectChatPreview },
  { id: "resources", title: "资源 / 任务", icon: resourcesIcon, render: (ctx) => <ResourcesTab ctx={ctx} />, preview: selectResourcesPreview },
  { id: "media", title: mediaInputLabels.title, icon: mediaIcon, render: (ctx) => <MediaInputTab ctx={ctx} />, preview: selectMediaPreview },
  { id: "variables", title: "会话变量", icon: variablesIcon, render: (ctx) => <VariablesTab ctx={ctx} />, preview: selectVariablesPreview },
  { id: "subagents", title: "子会话", icon: subagentsIcon, render: (ctx) => <SubagentsTab ctx={ctx} />, preview: selectSubagentsPreview },
  { id: "characters", title: "角色档案", icon: charactersIcon, render: (ctx) => <CharactersTab ctx={ctx} />, preview: selectCharactersPreview },
  { id: "site", title: "会话网页", icon: siteIcon, render: (ctx) => <SiteTab ctx={ctx} />, preview: selectSitePreview },
  { id: "llm", title: "模型配置", icon: llmIcon, render: (ctx) => <LlmTab ctx={ctx} />, preview: selectLlmPreview },
  { id: "sandbox", title: "动态沙盒空间", icon: sandboxIcon, render: (ctx) => <SandboxTab ctx={ctx} />, preview: selectSandboxPreview },
];
