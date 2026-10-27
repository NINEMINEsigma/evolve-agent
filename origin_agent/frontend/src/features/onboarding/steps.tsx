import type { Step } from "react-joyride";
import { ONBOARDING_STEPS, ONBOARDING_TAB_GROUPS } from "./constants";
import { onboardingLabels as labels } from "./labels";
import type { OnboardingStepsOptions } from "./types";

export function buildOnboardingSteps({ archived, isMobile, tabs, prepare }: OnboardingStepsOptions): Step[] {
  const grouped = ONBOARDING_TAB_GROUPS.flatMap((group) => group.tabs);
  if (grouped.length !== tabs.length || new Set(grouped).size !== grouped.length
    || tabs.some((tab) => !grouped.includes(tab.id))) {
    throw new Error("Onboarding tab groups must cover the tab registry exactly once");
  }
  return ONBOARDING_STEPS.map((definition) => {
    const { id } = definition;
    const text = labels.steps[id];
    const archivedInput = archived && (id === "input" || id === "approval");
    return {
      id,
      target: archivedInput ? "body" : definition.target,
      title: text.title,
      placement: archivedInput || (isMobile && definition.mobileCentered) ? "center" : definition.placement,
      content: (
        <div className="onboarding-copy">
          {archivedInput && <p className="onboarding-callout">{labels.steps[id === "input" ? "input" : "approval"].archived}</p>}
          {text.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
          {id === "sidebar" && <p>{isMobile ? labels.steps.sidebar.mobile : labels.steps.sidebar.desktop}</p>}
          {id === "tabs" && (
            <dl className="onboarding-tab-groups">
              {ONBOARDING_TAB_GROUPS.map((group) => (
                <div key={group.label}>
                  <dt>{labels.groups[group.label]}</dt>
                  <dd>{group.tabs.map((tabId) => {
                    const tab = tabs.find((item) => item.id === tabId);
                    if (!tab) throw new Error("Missing onboarding tab title");
                    return <span key={tabId}>{tab.title}</span>;
                  })}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ),
      before: () => prepare(id),
    };
  });
}
