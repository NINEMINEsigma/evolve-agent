import { useEffect, useRef, useState } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { ROUND_NAV_ENTRY_HEIGHT_PX } from "../constants/roundNav";
import type { RoundNavEntry } from "../features/chat/roundNav";

interface RoundNavRailProps {
  entries: RoundNavEntry[];
  currentEntryId: string | null;
  onJump: (entry: RoundNavEntry) => void;
}

/**
 * Round navigation rail: one entry per user message, bar-only by default,
 * expanding into an overlay with entry text on desktop hover/focus.
 * Clicking an entry jumps to the corresponding message.
 */
export default function RoundNavRail({ entries, currentEntryId, onJump }: RoundNavRailProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const hoveredRef = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [availableHeight, setAvailableHeight] = useState(0);

  const hasEntries = entries.length > 0;

  // Root only exists once entries render; re-attach the observer when it appears.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const update = () => {
      const styles = getComputedStyle(root);
      setAvailableHeight(root.clientHeight - parseFloat(styles.paddingTop || "0"));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(root);
    return () => observer.disconnect();
  }, [hasEntries]);

  // Keep the current round visible; suspended while the user browses the rail.
  useEffect(() => {
    if (!currentEntryId || hoveredRef.current) return;
    const index = entries.findIndex((entry) => entry.entryId === currentEntryId);
    if (index < 0) return;
    virtuosoRef.current?.scrollToIndex({ index, align: "center", behavior: "auto" });
  }, [currentEntryId, entries]);

  if (entries.length === 0) return null;

  // Fewer entries than the viewport: hug the content height so the list centers vertically.
  const listHeight = availableHeight > 0
    ? Math.min(entries.length * ROUND_NAV_ENTRY_HEIGHT_PX, availableHeight)
    : 0;

  const setHovered = (value: boolean) => {
    hoveredRef.current = value;
    setExpanded(value);
  };

  return (
    <div
      ref={rootRef}
      className={`round-nav${expanded ? " round-nav--expanded" : ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHovered(false);
      }}
    >
      {/* The wrap div is fully ours (no library inline styles), carrying the
          absolute centering and the expanded overlay width; Virtuoso just fills it. */}
      <div className="round-nav-list-wrap" style={{ height: listHeight }}>
        <Virtuoso
          ref={virtuosoRef}
          className="round-nav-list"
          data={entries}
          fixedItemHeight={ROUND_NAV_ENTRY_HEIGHT_PX}
          computeItemKey={(_index, entry) => entry.entryId}
          itemContent={(_index, entry) => (
            <div
              className={`round-nav-entry${entry.entryId === currentEntryId ? " round-nav-entry--current" : ""}`}
              data-tooltip={entry.tooltip || undefined}
              role="button"
              tabIndex={0}
              onClick={() => onJump(entry)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onJump(entry);
                }
              }}
            >
              <div className="round-nav-bar" style={{ backgroundColor: `hsl(${entry.hue}, 65%, 45%)` }} />
              <span className="round-nav-text">{entry.text}</span>
            </div>
          )}
        />
      </div>
    </div>
  );
}
