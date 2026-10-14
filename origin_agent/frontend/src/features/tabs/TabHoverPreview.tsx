/**
 * Read-only hover preview card. Renders one PopupLayer with role="tooltip";
 * PopupLayer's own outside-click/ESC closing is disabled because the hover
 * state machine owns every dismissal path. No buttons, inputs, focus trap,
 * aria-live countdown or auto-scroll: click on the card never switches tabs.
 */
import type { ReactElement } from "react";
import PopupLayer from "../../components/primitives/PopupLayer";
import type { TabDefinition, TabId } from "./registry";
import type { HoverPreviewState } from "../../hooks/useAnchoredHoverPreview";
import type { TabPreviewModel, TabPreviewRow } from "./tabPreviewTypes";

interface TabHoverPreviewProps {
  tab: TabDefinition;
  model: TabPreviewModel;
  hover: HoverPreviewState<TabId>;
  tooltipId: string;
}

function parsePercent(value: string): number | null {
  const match = /(\d+)%\s*$/.exec(value);
  return match ? Math.max(0, Math.min(100, Number(match[1]))) : null;
}

function MediaProgressRow({ row, tone }: { row: TabPreviewRow; tone: "enabled" | "disabled" }): ReactElement {
  const percent = parsePercent(row.value) ?? 0;
  return (
    <div className="tab-hover-preview-progress">
      <div className="tab-hover-preview-progress-meta">
        <span className={`tab-hover-preview-progress-label progress-${tone}`}>{row.label}</span>
        <span className="tab-hover-preview-progress-value">{row.value}</span>
      </div>
      <div
        className={`tab-hover-preview-progress-track progress-${tone}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div className={`tab-hover-preview-progress-fill progress-${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export default function TabHoverPreview({ tab, model, hover, tooltipId }: TabHoverPreviewProps): ReactElement {
  const media = tab.id === "media";
  return (
    <PopupLayer
      className="tab-hover-preview"
      position={hover.position}
      closeOnOutsideClick={false}
      closeOnEsc={false}
      containerRef={hover.surfaceRef}
    >
      <div
        className="tab-hover-preview-inner"
        id={tooltipId}
        role="tooltip"
        style={{
          width: `${hover.width}px`,
          maxHeight: `${hover.maxHeight}px`,
          visibility: hover.positioned ? "visible" : "hidden",
        }}
        {...hover.surfaceProps}
      >
        <div className="tab-hover-preview-title">{tab.title}</div>
        {model.sections.map((section) => (
          <div key={section.key} className={`tab-hover-preview-section tab-hover-preview-section-${section.key}`}>
            {section.title && <div className="tab-hover-preview-section-title">{section.title}</div>}
            {section.rows.map((row) => {
              if (media && (row.key === "media-enabled" || row.key === "media-disabled")) {
                return <MediaProgressRow key={row.key} row={row} tone={row.key === "media-enabled" ? "enabled" : "disabled"} />;
              }
              return (
                <div key={row.key} className={`tab-hover-preview-row tone-${row.tone}`}>
                  <span className="tab-hover-preview-row-label">{row.label}</span>
                  <span className="tab-hover-preview-row-value">{row.value}</span>
                </div>
              );
            })}
            {section.notice && <div className="tab-hover-preview-notice">{section.notice}</div>}
          </div>
        ))}
        {model.footnote && <div className="tab-hover-preview-footnote">{model.footnote}</div>}
      </div>
    </PopupLayer>
  );
}