import type { ChatMessage } from "../../types";
import { hueFromString } from "../../utils/color";
import {
  ROUND_NAV_EXCERPT_MAX_CHARS,
  ROUND_NAV_TOOLTIP_MAX_CHARS,
} from "../../constants/roundNav";
import { contentToText } from "./messageCollapse";
import type { ChatRenderRow } from "./types";

/** One user-message round entry of the round navigation rail. */
export interface RoundNavEntry {
  /** user row renderId (main chat) or message id (subagent card) */
  entryId: string;
  /** display row index (main chat) or messages array index (subagent card) */
  rowIndex: number;
  /** author character name with "User" fallback */
  characterName: string;
  /** avatar-consistent hue from the author character name */
  hue: number;
  /** entry text truncated to ROUND_NAV_EXCERPT_MAX_CHARS */
  text: string;
  /** fuller tooltip text truncated to ROUND_NAV_TOOLTIP_MAX_CHARS */
  tooltip: string;
}

/** Collapse whitespace and truncate with an ellipsis. */
export function truncateRoundNavText(raw: string, maxChars: number): string {
  const flat = raw.replace(/\s+/g, " ").trim();
  if (flat.length <= maxChars) return flat;
  return flat.slice(0, maxChars) + "…";
}

function buildEntry(entryId: string, rowIndex: number, characterName: string, raw: string): RoundNavEntry {
  return {
    entryId,
    rowIndex,
    characterName,
    hue: hueFromString(characterName),
    text: truncateRoundNavText(raw, ROUND_NAV_EXCERPT_MAX_CHARS),
    tooltip: truncateRoundNavText(raw, ROUND_NAV_TOOLTIP_MAX_CHARS),
  };
}

/** Build rail entries from the main-chat display rows (user rows only). */
export function buildRoundNavEntries(rows: ChatRenderRow[]): RoundNavEntry[] {
  const entries: RoundNavEntry[] = [];
  rows.forEach((row, rowIndex) => {
    const role = row.skeleton?.role ?? row.message?.role ?? "";
    if (role !== "user") return;
    const characterName = row.skeleton?.character_name ?? row.message?.characterName ?? "User";
    const raw = row.message ? contentToText(row.message.content) : (row.skeleton?.content_excerpt ?? "");
    entries.push(buildEntry(row.renderId, rowIndex, characterName, raw));
  });
  return entries;
}

/** Build rail entries from a subagent card's local messages (user rows only). */
export function buildRoundNavEntriesFromMessages(messages: ChatMessage[]): RoundNavEntry[] {
  const entries: RoundNavEntry[] = [];
  messages.forEach((message, rowIndex) => {
    if (message.role !== "user") return;
    entries.push(buildEntry(message.id, rowIndex, message.characterName ?? "User", contentToText(message.content)));
  });
  return entries;
}

/**
 * Resolve the current round: the last entry at or above the top visible row,
 * falling back to the first entry. Returns null when there are no entries.
 */
export function resolveCurrentRoundEntryId(entries: RoundNavEntry[], topVisibleRowIndex: number): string | null {
  if (entries.length === 0) return null;
  let current: RoundNavEntry | null = null;
  for (const entry of entries) {
    if (entry.rowIndex > topVisibleRowIndex) break;
    current = entry;
  }
  return (current ?? entries[0]).entryId;
}
