#!/usr/bin/env python3
"""
Load a SillyTavern world book from JSON file.
Entries are activated when their keys appear in the context.

Usage:
    python load_world.py <path-to-world-book> [--output-json <path>]
"""
import json, sys, argparse
from pathlib import Path

def load_world_book(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"World book file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"entries": data, "name": file_path.stem}
    elif "entries" in data:
        return data
    elif "data" in data and "entries" in data["data"]:
        return {"name": data.get("name", file_path.stem), "entries": data["data"]["entries"], "description": data.get("description", "")}
    else:
        raise ValueError("Unrecognized world book format")

def normalize_entry(entry: dict) -> dict:
    keys = entry.get("keys", entry.get("key", []))
    if isinstance(keys, str):
        keys = [keys]
    content = entry.get("content", entry.get("value", ""))
    position = entry.get("position", entry.get("placement", "after_char"))
    order = entry.get("order", entry.get("insertion_order", 0))
    if isinstance(order, str):
        try: order = int(order)
        except ValueError: order = 0
    return {
        "id": entry.get("id", entry.get("uid", 0)),
        "keys": keys, "content": content,
        "comment": entry.get("comment", entry.get("name", "")),
        "enabled": entry.get("enabled", True),
        "position": position, "order": order,
        "case_sensitive": entry.get("case_sensitive", False),
        "priority": entry.get("priority", entry.get("weight", 0)),
        "constant": entry.get("constant", entry.get("always_on", False)),
        "selective": entry.get("selective", False),
        "selectiveLogic": entry.get("selectiveLogic", 0),
        "extensions": entry.get("extensions", {}),
    }

def normalize_world_book(raw: dict) -> dict:
    entries = []
    for entry in raw.get("entries", []):
        try: entries.append(normalize_entry(entry))
        except Exception as e: print(f"Warning: {e}", file=sys.stderr)
    return {"name": raw.get("name", "Unnamed World"), "description": raw.get("description", ""), "entries": entries, "entry_count": len(entries)}

def match_entries(world_book: dict, context: str, max_entries: int = 50) -> list:
    matched = []
    context_lower = context.lower()
    for entry in world_book.get("entries", []):
        if not entry.get("enabled", True): continue
        if entry.get("constant", False):
            matched.append(entry); continue
        keys = entry.get("keys", [])
        case_sensitive = entry.get("case_sensitive", False)
        for key in keys:
            if not key: continue
            if case_sensitive:
                if key in context: matched.append(entry); break
            else:
                if key.lower() in context_lower: matched.append(entry); break
    matched.sort(key=lambda e: (-e.get("priority", 0), -e.get("order", 0)))
    return matched[:max_entries]

def main():
    parser = argparse.ArgumentParser(description="Load SillyTavern world book")
    parser.add_argument("world_path", help="Path to world book JSON")
    parser.add_argument("--output-json", "-o", help="Output file")
    parser.add_argument("--raw", action="store_true", help="Output raw")
    parser.add_argument("--match-context", "-m", help="Filter entries matching context")
    parser.add_argument("--max-entries", type=int, default=50, help="Max matched entries")
    args = parser.parse_args()
    try:
        raw = load_world_book(args.world_path)
        output = raw if args.raw else normalize_world_book(raw)
        if args.match_context:
            matched = match_entries(output, args.match_context, args.max_entries)
            output = {"name": output.get("name", ""), "matched_count": len(matched), "matched_entries": matched}
        json_str = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f: f.write(json_str)
            print(f"Saved to {args.output_json}", file=sys.stderr)
        else: print(json_str)
    except Exception as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()