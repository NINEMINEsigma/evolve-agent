#!/usr/bin/env python3
"""
Load a SillyTavern character card from PNG or JSON file.
PNG cards embed JSON data in a tEXt chunk with key "chara" (base64 encoded).
JSON cards are direct JSON files.

Usage:
    python load_card.py <path-to-card> [--output-json <path>]
"""
import json, base64, sys, zlib, argparse
from pathlib import Path

def extract_from_png(png_path: str) -> dict:
    with open(png_path, "rb") as f:
        data = f.read()
    offset = 8
    while offset < len(data):
        length = int.from_bytes(data[offset:offset+4], "big")
        chunk_type = data[offset+4:offset+8].decode("ascii", errors="replace")
        chunk_data = data[offset+8:offset+8+length]
        offset += 12 + length
        if chunk_type == "tEXt":
            try:
                text = chunk_data.decode("latin-1")
                if "\x00" in text:
                    key, value = text.split("\x00", 1)
                    if key == "chara":
                        decoded = base64.b64decode(value)
                        try:
                            decompressed = zlib.decompress(decoded)
                            return json.loads(decompressed.decode("utf-8"))
                        except zlib.error:
                            return json.loads(decoded.decode("utf-8"))
            except Exception:
                pass
    raise ValueError("No 'chara' tEXt chunk found in PNG file")

def load_card(card_path: str) -> dict:
    path = Path(card_path)
    if not path.exists():
        raise FileNotFoundError(f"Card file not found: {card_path}")
    if path.suffix.lower() == ".png":
        return extract_from_png(str(path))
    elif path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return extract_from_png(str(path))

def normalize_card(raw: dict) -> dict:
    if "data" in raw:
        data = raw["data"]
        if "character" in data:
            char = data["character"]
            card = {
                "name": char.get("name", "Unknown"),
                "description": char.get("description", ""),
                "personality": char.get("personality", ""),
                "scenario": char.get("scenario", ""),
                "first_mes": char.get("first_mes", char.get("firstMessage", "")),
                "mes_example": char.get("mes_example", char.get("mesExample", "")),
                "system_prompt": char.get("system_prompt", ""),
                "post_history_instructions": char.get("post_history_instructions", ""),
                "extensions": char.get("extensions", {}),
            }
            if "character_book" in data:
                card["embedded_world_book"] = data["character_book"]
            return card
        else:
            char = data
    else:
        char = raw
    return {
        "name": char.get("name", "Unknown"),
        "description": char.get("description", ""),
        "personality": char.get("personality", ""),
        "scenario": char.get("scenario", ""),
        "first_mes": char.get("first_mes", char.get("firstMessage", "")),
        "mes_example": char.get("mes_example", char.get("mesExample", "")),
        "system_prompt": char.get("system_prompt", ""),
        "post_history_instructions": char.get("post_history_instructions", ""),
        "extensions": char.get("extensions", {}),
    }

def main():
    parser = argparse.ArgumentParser(description="Load SillyTavern character card")
    parser.add_argument("card_path", help="Path to .png or .json character card")
    parser.add_argument("--output-json", "-o", help="Output to JSON file")
    parser.add_argument("--raw", action="store_true", help="Output raw card")
    args = parser.parse_args()
    try:
        raw = load_card(args.card_path)
        output = raw if args.raw else normalize_card(raw)
        json_str = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"Card saved to {args.output_json}", file=sys.stderr)
        else:
            print(json_str)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()