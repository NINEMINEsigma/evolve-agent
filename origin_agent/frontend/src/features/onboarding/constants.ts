import type { TabId } from "../tabs/registry";
import type { OnboardingPresentation, OnboardingStepDefinition } from "./types";

export const ONBOARDING = {
  TARGET_TIMEOUT_MS: 2000,
  BEFORE_TIMEOUT_MS: 2500,
  STABLE_FRAMES: 2,
  GEOMETRY_TOLERANCE_PX: 0.25,
  SPOTLIGHT_PADDING_PX: 8,
  RADIUS_PX: 14,
  MAX_WIDTH_PX: 380,
  VIEWPORT_MARGIN_PX: 12,
  Z_INDEX: 10000,
  SCROLL_DURATION_MS: 300,
  ROOT_SELECTOR: "[data-onboarding-root]",
  COMMAND_SELECTOR: '[data-tour="command-menu"]',
  DIALOG_SELECTOR: '[role="dialog"][aria-modal="true"]',
} as const;

export const EMPTY_PRESENTATION: OnboardingPresentation = {
  stepId: null, expandSidebar: false, expandInput: false,
};

export const ONBOARDING_STEPS: readonly OnboardingStepDefinition[] = [
  { id: "welcome", target: "body", tab: "chat", placement: "center" },
  { id: "sidebar", target: '[data-tour="sidebar"]', tab: "chat", placement: "right", mobileCentered: true },
  { id: "header", target: '[data-tour="header"]', tab: "chat", placement: "bottom" },
  // 完整面板四周没有足够空间，卡片在视口居中，目标仍用于面板高亮。
  { id: "model-config", target: '[data-tour="llm-tab"]', tab: "llm", placement: "center" },
  { id: "model-selection", target: '[data-tour="model-selection"]', tab: "chat", placement: "bottom" },
  { id: "input", target: '[data-tour="input-surface"]', tab: "chat", placement: "top", mobileCentered: true },
  { id: "approval", target: '[data-tour="approval-mode"] .input-approval-mode', tab: "chat", placement: "top" },
  { id: "tabs", target: '[data-tour="tab-rail"]', tab: "chat", placement: "left", mobileCentered: true },
  { id: "resources", target: '[data-tour="resources-tab"]', tab: "resources", placement: "center" },
  { id: "sandbox", target: '[data-tour="sandbox-tab"]', tab: "sandbox", placement: "center" },
  { id: "commands", target: '[data-tour="tab-rail-footer"]', tab: "chat", placement: "left" },
];

export const ONBOARDING_TAB_GROUPS: readonly {
  label: "conversation" | "content" | "configuration";
  tabs: readonly TabId[];
}[] = [
  { label: "conversation", tabs: ["chat", "subagents", "characters"] },
  { label: "content", tabs: ["resources", "changes", "media", "variables", "site"] },
  { label: "configuration", tabs: ["llm", "sandbox", "activity"] },
];
