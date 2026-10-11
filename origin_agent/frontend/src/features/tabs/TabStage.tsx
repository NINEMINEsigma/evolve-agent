import { useEffect, useRef } from "react";
import type { TabDefinition, TabId, TabRenderContext } from "./registry";

interface TabStageProps {
  tabs: readonly TabDefinition[];
  activeTab: TabId;
  renderContext: TabRenderContext;
}

/**
 * Main tab stage: all tab layers stay mounted in one grid cell and switch
 * via `visibility` so chat scroll positions and iframes survive switches.
 */
export default function TabStage({ tabs, activeTab, renderContext }: TabStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);

  // Keyboard focus safety net: a focused element inside the freshly hidden
  // site iframe could keep receiving keystrokes. Blur it on every switch.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const layer = stage.querySelector<HTMLElement>('[data-tab-panel="site"]');
    const iframe = layer?.querySelector("iframe");
    if (iframe) {
      try {
        (iframe as HTMLIFrameElement).blur();
        (iframe as HTMLIFrameElement).contentWindow?.blur();
      } catch {
        // cross-origin iframe blur failures are harmless; browser focus rules still apply
      }
    }
  }, [activeTab]);

  return (
    <div className="tab-stage" ref={stageRef}>
      {tabs.map((tab) => {
        const active = tab.id === activeTab;
        return (
          <div
            key={tab.id}
            className="tab-panel-layer"
            data-tab-panel={tab.id}
            data-active={active}
          >
            {tab.render(renderContext)}
          </div>
        );
      })}
    </div>
  );
}
