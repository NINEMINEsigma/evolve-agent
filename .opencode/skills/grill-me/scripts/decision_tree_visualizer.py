#!/usr/bin/env python3
"""
Decision Tree Visualizer for grill-me-pro

Converts a decision-log.md into a visual decision tree diagram.
Supports Mermaid, ASCII art, and DOT (Graphviz) output formats.

Usage:
    python decision_tree_visualizer.py decision-log.md --format mermaid
    python decision_tree_visualizer.py decision-log.md --format ascii
    python decision_tree_visualizer.py decision-log.md --format dot > tree.dot
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_decision_log(content: str) -> list[dict]:
    """Parse decision-log.md and extract decisions with their relationships.

    Uses a robust parser that does NOT depend on field order or separator style.
    Finds all decision sections by their ### D{n}: header, then extracts fields
    within each section until the next decision header or major section boundary.
    """
    decisions = []

    # Find all decision headers: ### D1: Title
    header_pattern = re.compile(r'^### (D\d+):\s*(.+?)$', re.MULTILINE)
    headers = list(header_pattern.finditer(content))

    for i, header in enumerate(headers):
        decision_id = header.group(1)
        title = header.group(2).strip()

        # Determine the block content: from end of this header to start of next header
        start = header.end()
        if i + 1 < len(headers):
            end = headers[i + 1].start()
        else:
            end = len(content)
        block = content[start:end]

        # Extract all **Field**: value pairs from the block
        # Match **Field Name**: value (value continues until next **Field** or end of block)
        fields = {}
        field_pattern = re.compile(r'\*\*(.+?)\*\*:\s*(.+?)(?=\n\*\*|$)', re.DOTALL)
        for fm in field_pattern.finditer(block):
            field_name = fm.group(1).strip().lower().replace(' ', '_')
            field_value = fm.group(2).strip()
            fields[field_name] = field_value

        # Normalize 'none' downstream to empty
        downstream = fields.get('downstream_impact', '')
        if downstream.lower().startswith('none'):
            downstream = ''

        decisions.append({
            'id': decision_id,
            'title': title,
            'status': fields.get('status', '[OPEN]'),
            'question': fields.get('question', ''),
            'answer': fields.get('answer', ''),
            'tradeoff': fields.get('trade-off_accepted', ''),
            'downstream': downstream,
        })

    return decisions


def build_tree(decisions: list[dict]) -> tuple[dict[str, list[str]], set[str]]:
    """Build parent-child relationships from downstream impact mentions.
    
    Parses downstream impact field to find explicit decision references.
    "D2 (description), D3 (description)" means current decision is parent of D2 and D3.
    
    Returns:
        tree: dict mapping parent_id -> list of child_ids
        roots: set of root decision IDs (no parents)
    """
    id_set = {d["id"] for d in decisions}
    
    # parents[child] = list of parents
    parents: dict[str, list[str]] = {d["id"]: [] for d in decisions}
    
    for d in decisions:
        downstream = d.get("downstream", "")
        if not downstream:
            continue
        # Split by comma/semicolon and extract leading decision IDs
        parts = re.split(r'[,;]', downstream)
        for part in parts:
            part = part.strip()
            # Match decision ID at the start of each part
            match = re.match(r'^(D\d+)\b', part)
            if match:
                other_id = match.group(1)
                if other_id in id_set and other_id != d["id"]:
                    if d["id"] not in parents[other_id]:
                        parents[other_id].append(d["id"])
    
    # Convert to tree (parent -> children)
    tree: dict[str, list[str]] = {d["id"]: [] for d in decisions}
    for child_id, parent_ids in parents.items():
        for parent_id in parent_ids:
            if child_id not in tree[parent_id]:
                tree[parent_id].append(child_id)
    
    # Sort children for consistent output
    for parent_id in tree:
        tree[parent_id].sort()
    
    # Roots are decisions with no parents
    roots = {d["id"] for d in decisions if not parents[d["id"]]}
    
    return tree, roots


def status_icon(status: str) -> str:
    """Return a visual indicator for decision status."""
    if "RESOLVED" in status:
        return "[OK]"
    elif "RISKY" in status:
        return "[!]"
    elif "DEFERRED" in status:
        return "[>>]"
    return "[?]"


def status_emoji(status: str) -> str:
    """Return ASCII-safe status indicator for all output formats.

    Uses pure ASCII to avoid UnicodeEncodeError on Windows GBK terminals.
    Mermaid/DOT/ASCII formats all use this for consistent, portable output.
    """
    return status_icon(status)


def to_mermaid(decisions: list[dict], tree: dict[str, list[str]], roots: set[str]) -> str:
    """Generate Mermaid flowchart."""
    lines = ["```mermaid", "flowchart TD"]
    
    # Add nodes
    for d in decisions:
        icon = status_emoji(d["status"])
        safe_title = d["title"].replace('"', '\\"')
        lines.append(f'    {d["id"]}["{icon} {d["id"]}: {safe_title}"]')
    
    # Add edges
    for parent_id in sorted(tree.keys()):
        for child_id in tree[parent_id]:
            lines.append(f"    {parent_id} --> {child_id}")
    
    # Add style classes
    lines.append("")
    lines.append("    classDef resolved fill:#90EE90,stroke:#228B22")
    lines.append("    classDef risky fill:#FFD700,stroke:#FF8C00")
    lines.append("    classDef deferred fill:#87CEEB,stroke:#4169E1")
    lines.append("    classDef open fill:#FFB6C1,stroke:#DC143C")
    
    for d in decisions:
        if "RESOLVED" in d["status"]:
            lines.append(f"    class {d['id']} resolved")
        elif "RISKY" in d["status"]:
            lines.append(f"    class {d['id']} risky")
        elif "DEFERRED" in d["status"]:
            lines.append(f"    class {d['id']} deferred")
        else:
            lines.append(f"    class {d['id']} open")
    
    lines.append("```")
    return "\n".join(lines)


def to_ascii(decisions: list[dict], tree: dict[str, list[str]], roots: set[str]) -> str:
    """Generate ASCII art tree."""
    lines = ["Decision Tree", "=" * 50, ""]
    
    decision_map = {d["id"]: d for d in decisions}
    
    def render_node(node_id: str, prefix: str = "", is_last: bool = True) -> list[str]:
        result = []
        d = decision_map[node_id]
        icon = status_icon(d["status"])
        connector = "└── " if is_last else "├── "
        result.append(f"{prefix}{connector}{icon} {d['id']}: {d['title']}")
        
        children = tree.get(node_id, [])
        new_prefix = prefix + ("    " if is_last else "|   ")
        
        for i, child_id in enumerate(children):
            result.extend(render_node(child_id, new_prefix, i == len(children) - 1))
        
        return result
    
    for root_id in sorted(roots):
        lines.extend(render_node(root_id, "", True))
        lines.append("")
    
    lines.append("Legend: [OK]=Resolved [!]=Risky [>>]=Deferred [?]=Open")
    return "\n".join(lines)


def to_dot(decisions: list[dict], tree: dict[str, list[str]], roots: set[str]) -> str:
    """Generate Graphviz DOT format."""
    lines = [
        "digraph DecisionTree {",
        '    rankdir="TB";',
        '    node [shape=box, style="rounded,filled", fontname="Helvetica"];',
        '    edge [fontname="Helvetica"];',
        ""
    ]
    
    status_colors = {
        "RESOLVED": "#90EE90",
        "RISKY": "#FFD700",
        "DEFERRED": "#87CEEB",
        "OPEN": "#FFB6C1",
    }
    
    for d in decisions:
        color = "#D3D3D3"
        for status_key, color_val in status_colors.items():
            if status_key in d["status"]:
                color = color_val
                break
        safe_title = d["title"].replace('"', '\\"')
        label = f"{status_emoji(d['status'])} {d['id']}:\\n{safe_title}"
        lines.append(f'    {d["id"]} [label="{label}", fillcolor="{color}"];')
    
    for parent_id in sorted(tree.keys()):
        for child_id in tree[parent_id]:
            lines.append(f"    {parent_id} -> {child_id};")
    
    lines.append("}")
    return "\n".join(lines)


def _set_utf8_stdout() -> None:
    """Force UTF-8 encoding on stdout to prevent UnicodeEncodeError
    on Windows GBK terminals and other non-UTF-8 environments."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # Fallback for StringIO or other non-file stdout objects
        pass


def main() -> int:
    _set_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Visualize grill-me-pro decision logs as decision trees"
    )
    parser.add_argument("input_file", type=Path, help="Path to decision-log.md")
    parser.add_argument(
        "--format",
        choices=["mermaid", "ascii", "dot"],
        default="mermaid",
        help="Output format (default: mermaid)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: stdout)")
    args = parser.parse_args()
    
    if not args.input_file.exists():
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        return 1
    
    content = args.input_file.read_text(encoding="utf-8")
    decisions = parse_decision_log(content)
    
    if not decisions:
        print("Warning: No decisions found in the log file.", file=sys.stderr)
        return 1
    
    tree, roots = build_tree(decisions)
    
    if args.format == "mermaid":
        output = to_mermaid(decisions, tree, roots)
    elif args.format == "ascii":
        output = to_ascii(decisions, tree, roots)
    elif args.format == "dot":
        output = to_dot(decisions, tree, roots)
    else:
        output = to_mermaid(decisions, tree, roots)
    
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Output written to {args.output}")
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
