import type { Step } from "react-joyride";
import type { TabId } from "../tabs/registry";

export type OnboardingStepId =
  | "welcome" | "sidebar" | "header" | "model-config" | "model-selection"
  | "input" | "approval" | "tabs" | "resources" | "sandbox" | "commands";

export type OnboardingExitReason = "completed" | "skipped" | "interrupted" | "failed";

export interface OnboardingRun {
  id: number;
  sessionId: string;
  source: "first-visit" | "replay";
  initialTab: TabId;
  initialFocus: HTMLElement | null;
}

export interface OnboardingPresentation {
  stepId: OnboardingStepId | null;
  expandSidebar: boolean;
  expandInput: boolean;
}

export interface OnboardingEnvironment {
  ready: boolean;
  sessionId: string;
  locked: boolean;
  busy: boolean;
  hasPendingInteraction: boolean;
  blocked: boolean;
  // 命令菜单本身阻挡启动，但不能禁用菜单内的重看按钮。
  commandMenuOpen: boolean;
  archived: boolean;
  isMobile: boolean;
  activeTab: TabId;
  enabledTabs: Record<TabId, boolean>;
}

export interface OnboardingAdapters {
  switchTab: (id: TabId) => void;
  onNotice: (message: string) => void;
}

export interface OnboardingTourController {
  run: OnboardingRun | null;
  presentation: OnboardingPresentation;
  preparing: boolean;
  renderEpoch: number;
  canReplay: boolean;
  replayDisabledReason: string;
  requestReplay: () => void;
  prepareStep: (id: OnboardingStepId) => Promise<void>;
  finish: (reason: OnboardingExitReason) => void;
  reportFailure: (error: unknown) => void;
}

export interface OnboardingStepsOptions {
  archived: boolean;
  isMobile: boolean;
  tabs: readonly { id: TabId; title: string }[];
  prepare: (id: OnboardingStepId) => Promise<void>;
}

export interface OnboardingStepDefinition {
  id: OnboardingStepId;
  target: string;
  tab: TabId;
  placement: Step["placement"];
  mobileCentered?: boolean;
}
