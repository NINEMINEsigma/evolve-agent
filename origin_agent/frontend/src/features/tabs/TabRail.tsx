import type { ReactNode } from "react";
import type { TabDefinition, TabId, TabRenderContext } from "./registry";
import { TAB_PREVIEW } from "../../constants/tabPreview";
import { useAnchoredHoverPreview } from "../../hooks/useAnchoredHoverPreview";
import { useTabPreview } from "./useTabPreview";
import TabHoverPreview from "./TabHoverPreview";

interface TabRailProps {
  tabs: readonly TabDefinition[];
  activeTab: TabId;
  enabledTabs: Record<TabId, boolean>;
  onSwitch: (id: TabId) => void;
  renderContext: TabRenderContext;
  previewBlocked: boolean;
  footer: ReactNode;
}

const TOOLTIP_ID = "tab-rail-preview";

/** Right-edge vertical tab rail. Always visible; disabled tabs are not clickable. */
export default function TabRail({ tabs, activeTab, enabledTabs, onSwitch, renderContext, previewBlocked, footer }: TabRailProps) {
  const scopeKey = JSON.stringify([renderContext.sessionId, activeTab]);
  const hover = useAnchoredHoverPreview<TabId>({
    scopeKey,
    blocked: previewBlocked,
    isEligible: (key) => enabledTabs[key] && key !== activeTab,
    showDelayMs: TAB_PREVIEW.SHOW_DELAY_MS,
    hideDelayMs: TAB_PREVIEW.HIDE_DELAY_MS,
    width: TAB_PREVIEW.WIDTH_PX,
    maxHeight: TAB_PREVIEW.MAX_HEIGHT_PX,
    anchorGap: TAB_PREVIEW.GAP_PX,
    viewportMargin: TAB_PREVIEW.VIEWPORT_MARGIN_PX,
  });

  const openTab = hover.openKey !== null
    ? tabs.find((tab) => tab.id === hover.openKey) ?? null
    : null;
  const model = useTabPreview(openTab, renderContext);

  return (
    <div className="tab-rail-column">
      <nav className="tab-rail" data-tour="tab-rail" aria-label="主界面视图切换">
        {tabs.map((tab) => {
          const enabled = enabledTabs[tab.id];
          const active = tab.id === activeTab;
          const eligible = enabled && !active;
          const showPreview = eligible && !previewBlocked && tab.preview !== undefined;
          return (
            <button
              key={tab.id}
              type="button"
              className="tab-rail-btn"
              data-tab-rail-id={tab.id}
              aria-current={active ? "page" : undefined}
              aria-describedby={hover.openKey === tab.id ? TOOLTIP_ID : undefined}
              disabled={!enabled}
              onClick={() => onSwitch(tab.id)}
              data-tooltip={showPreview ? undefined : tab.title}
              aria-label={tab.title}
              {...hover.getTriggerProps(tab.id)}
            >
              {tab.icon}
            </button>
          );
        })}
        {openTab !== null && model !== null && (
          <TabHoverPreview tab={openTab} model={model} hover={hover} tooltipId={TOOLTIP_ID} />
        )}
      </nav>
      {footer}
    </div>
  );
}