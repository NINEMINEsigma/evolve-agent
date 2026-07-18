import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export interface MentionItem {
  id: string;
  label: string;
  description?: string;
  icon?: "file" | "dir" | "skill";
}

interface MentionMenuProps {
  items: MentionItem[];
  selectedIndex: number;
  onSelect: (item: MentionItem) => void;
  position: { x: number; y: number; openUpward: boolean };
}

const ICON_SVG: Record<string, string> = {
  file: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  dir: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  skill: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
};

export default function MentionMenu({
  items,
  selectedIndex,
  onSelect,
  position,
}: MentionMenuProps) {
  const listRef = useRef<HTMLDivElement>(null);

  // 滚动选中项到可视区
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-idx="${selectedIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (items.length === 0) return null;

  // 用 Portal 渲染到 body，绕过祖先 transform 对 position:fixed 的降级
  return createPortal(
    <div
      className="mention-menu"
      style={{
        left: position.x,
        top: position.y,
        transform: position.openUpward ? "translateY(-100%)" : undefined,
      }}
      ref={listRef}
    >
      {items.map((item, i) => (
        <div
          key={item.id}
          data-idx={i}
          className={`mention-item${i === selectedIndex ? " active" : ""}`}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(item);
          }}
        >
          <span
            className="mention-item-icon"
            dangerouslySetInnerHTML={{
              __html: ICON_SVG[item.icon || "file"] || ICON_SVG.file,
            }}
          />
          <span className="mention-item-text">
            <span className="mention-item-label">{item.label}</span>
            {item.description && (
              <span className="mention-item-desc">{item.description}</span>
            )}
          </span>
        </div>
      ))}
    </div>,
    document.body,
  );
}