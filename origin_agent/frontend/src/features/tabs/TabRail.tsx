import type { TabDefinition, TabId } from "./registry";

interface TabRailProps {
  tabs: readonly TabDefinition[];
  activeTab: TabId;
  enabledTabs: Record<TabId, boolean>;
  onSwitch: (id: TabId) => void;
}

/** Right-edge vertical tab rail. Always visible; disabled tabs are not clickable. */
export default function TabRail({ tabs, activeTab, enabledTabs, onSwitch }: TabRailProps) {
  return (
    <nav className="tab-rail" data-tour="tab-rail" aria-label="主界面视图切换">
      {tabs.map((tab) => {
        const enabled = enabledTabs[tab.id];
        const active = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            type="button"
            className="tab-rail-btn"
            data-tab-rail-id={tab.id}
            aria-current={active ? "page" : undefined}
            disabled={!enabled}
            onClick={() => onSwitch(tab.id)}
            data-tooltip={tab.title}
            aria-label={tab.title}
          >
            {tab.icon}
          </button>
        );
      })}
    </nav>
  );
}
