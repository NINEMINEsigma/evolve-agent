import { ClipboardDisplay } from "../types";

interface UnifiedPanelProps {
  clipboardDisplays: Record<string, ClipboardDisplay>;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function UnifiedPanel({
  clipboardDisplays,
  collapsed,
  onToggleCollapse,
}: UnifiedPanelProps) {
  const items = Object.values(clipboardDisplays);
  if (items.length === 0) return null;

  return (
    <div className={`unified-panel ${collapsed ? "collapsed" : ""}`}>
      <div className="panel-header" onClick={onToggleCollapse}>
        <span className="panel-header-title">
          剪切板 ({items.length})
        </span>
        <button className="panel-header-toggle">
          {collapsed ? "▼" : "▲"}
        </button>
      </div>

      {!collapsed && (
        <div className="unified-content">
          {items.map((cd) => (
            <div key={cd.display_id} className="clipboard-display-item">
              <div className="clipboard-display-header">
                <span className="clipboard-display-label">{cd.label}</span>
                <button
                  className="clipboard-display-copy"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(cd.content);
                    } catch {
                      // ignore
                    }
                  }}
                >
                  复制
                </button>
              </div>
              <pre className="clipboard-display-content">{cd.content}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}