import { ClipboardDisplay } from "../types";

interface ClipboardPanelProps {
  clipboardDisplays: Record<string, ClipboardDisplay>;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function ClipboardPanel({
  clipboardDisplays,
  collapsed,
  onToggleCollapse,
}: ClipboardPanelProps) {
  const values = Object.values(clipboardDisplays);
  if (values.length === 0) return null;

  return (
    <div className={`clipboard-display-panel ${collapsed ? "collapsed" : ""}`}>
      <div className="panel-header" onClick={onToggleCollapse}>
        <span className="panel-header-title">剪切板 ({values.length})</span>
        <button className="panel-header-toggle">
          {collapsed ? "▼" : "▲"}
        </button>
      </div>
      {!collapsed && values.map((cd) => (
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
  );
}