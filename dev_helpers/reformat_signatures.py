# Dev helper: reformat function signatures so that functions with >= 3
# parameters (including self) use one-parameter-per-line style, matching the
# reference sample in origin_agent/system/session_visual_resources.py.
#
# Format produced:
#     def foo(
#         self,
#         a: int,
#         b: str = "x"
#         ) -> Ret:
#
# Inline comments attached to a parameter line (or a standalone comment line
# between parameters) are preserved in place. Bare "*" and "/" separators are
# preserved in their original relative position.

import argparse
import ast
import os
import sys

sys.dont_write_bytecode = True

TARGET_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "origin_agent")


class Param:
    def __init__(self, text, default=None, is_vararg=False, is_kwarg=False):
        self.text = text          # "name: ann" without star, or with star
        self.default = default    # source text of default or None
        self.is_vararg = is_vararg
        self.is_kwarg = is_kwarg
        self.comments_before = []  # standalone comment lines that appeared
                                  # immediately before this param in the source
        self.inline_comment = None  # trailing "# ..." comment on the same line


class FuncSig:
    def __init__(self, path, node, source, indent):
        self.path = path
        self.node = node
        self.source = source
        self.indent = indent
        self.name = node.name
        self.lineno = node.lineno
        self.is_async = isinstance(node, ast.AsyncFunctionDef)

    def collect(self):
        a = self.node.args
        params = []
        for p in a.posonlyargs:
            params.append(Param(self._param_text(p), self._default_text(p)))
        self._posonly_count = len(a.posonlyargs)
        for p in a.args:
            params.append(Param(self._param_text(p), self._default_text(p)))
        if a.vararg is not None:
            params.append(Param(self._param_text(a.vararg, with_star=True),
                                is_vararg=True))
        for p in a.kwonlyargs:
            params.append(Param(self._param_text(p), self._default_text(p)))
        if a.kwarg is not None:
            params.append(Param(self._param_text(a.kwarg, with_star=True),
                                is_kwarg=True))
        self.params = params
        return params

    def _get_source_segment(self, node):
        try:
            return ast.get_source_segment(self.source, node)
        except Exception:
            return None

    def _default_text(self, arg):
        if arg is None:
            return None
        a = self.node.args
        defaults = a.defaults
        all_pos = a.posonlyargs + a.args
        if arg in all_pos:
            idx = all_pos.index(arg)
            dpos = len(all_pos) - len(defaults)
            if idx >= dpos:
                return self._get_source_segment(defaults[idx - dpos])
            return None
        if arg in a.kwonlyargs:
            idx = a.kwonlyargs.index(arg)
            if idx < len(a.kw_defaults) and a.kw_defaults[idx] is not None:
                return self._get_source_segment(a.kw_defaults[idx])
            return None
        return None

    def _param_text(self, arg, with_star=False):
        ann = ""
        if arg.annotation is not None:
            seg = self._get_source_segment(arg.annotation) or ""
            ann = " ".join(seg.split())
        if with_star:
            star = "**" if arg is self.node.args.kwarg else "*"
        else:
            star = ""
        return f"{star}{arg.arg}: {ann}" if ann else f"{star}{arg.arg}"

    def _header_end_line(self):
        """1-based line number of the line containing the signature's colon.

        The colon is located only after the def's opening parenthesis has been
        fully closed, so parameter-annotation colons (depth 0 inside the paren
        span, e.g. ``def foo(a: int,``) do not terminate the scan early.
        """
        seg = self.source.splitlines()
        # skip past the def's name to its opening paren
        prefix = "async def" if self.is_async else "def"
        pos = seg[self.lineno - 1].find(prefix) + len(prefix)
        pos = seg[self.lineno - 1].find("(", pos)
        state = "before_paren" if pos == -1 else "in_paren"
        if pos == -1:
            pos = 0
        depth = 0
        in_str = None
        i = pos
        for li in range(self.lineno - 1, len(seg)):
            line = seg[li]
            start = pos if li == self.lineno - 1 else 0
            i = start
            while i < len(line):
                c = line[i]
                if in_str:
                    if c == "\\":
                        i += 2
                        continue
                    if c == in_str:
                        in_str = None
                elif c in "\"'":
                    in_str = c
                elif state == "before_paren":
                    if c == "(":
                        state = "in_paren"
                        depth = 1
                elif state == "in_paren":
                    if c in "([{":
                        depth += 1
                    elif c in ")]}":
                        depth -= 1
                        if depth == 0:
                            state = "after_paren"
                elif state == "after_paren":
                    if c == ":":
                        return li + 1
                i += 1
        raise RuntimeError(f"cannot find header end for {self.path}:{self.lineno}")

    def _scan_source_params(self):
        """Walk the raw header lines and extract, per parameter slot, the
        inline comment and any standalone comment lines preceding it.

        Returns (ordered list of comment-attached slots aligned with
        self.params, plus the position of a bare '*' or '/' separator if any).
        """
        start = self.lineno - 1
        end = self._header_end_line()
        lines = self.source.splitlines()[start:end]

        # Collect raw entries: ('param', text) / ('comment', text)
        entries = []  # (kind, text)
        pending_comments = []
        bare_star_index = None       # position in params list for bare '*'
        bare_slash_index = None      # position in params list for bare '/'

        param_slot = 0
        open_paren_seen = False
        for raw in lines:
            line = raw.rstrip("\n")
            stripped = line.strip()
            # skip the "def name(" prefix line
            if not open_paren_seen:
                idx = line.find("(")
                if idx == -1:
                    continue
                rest = line[idx + 1:].strip()
                open_paren_seen = True
                if not rest:
                    continue
                # there is content on the def line itself (single-line signature
                # case) - fall through with rest as the "line"
                stripped = rest
                line = rest
            if stripped.startswith("#"):
                pending_comments.append(stripped)
                continue
            # tokenize the line into comma-separated param fragments with
            # their trailing comments; bracket-aware split
            for frag, comment in self._split_params_with_comments(line):
                frag_s = frag.strip()
                if not frag_s:
                    # comment attached to a trailing comma fragment: keep it
                    # with the most recently scanned parameter
                    if comment and param_slot > 0:
                        target = self.params[param_slot - 1]
                        if target.inline_comment is None:
                            target.inline_comment = comment
                    continue
                if frag_s == "*":
                    bare_star_index = param_slot
                    param_slot += 1  # separator occupies a render slot
                    continue
                if frag_s == "/":
                    bare_slash_index = param_slot
                    param_slot += 1
                    continue
                # a real parameter
                if param_slot < len(self.params):
                    p = self.params[param_slot]
                    p.comments_before = pending_comments
                    p.inline_comment = comment
                    pending_comments = []
                param_slot += 1
        return bare_star_index, bare_slash_index

    def _split_params_with_comments(self, line):
        """Split a header line into (fragment, trailing_comment) pairs.
        Bracket- and string-aware. Returns a list of tuples."""
        results = []
        depth = 0
        in_str = None
        frag_start = 0
        i = 0
        n = len(line)
        while i < n:
            c = line[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c in "\"'":
                in_str = c
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == "#" and depth == 0:
                # comment to end of line - everything before is one fragment
                results.append((line[frag_start:i], line[i:].rstrip()))
                return results
            elif c == "," and depth == 0:
                results.append((line[frag_start:i], None))
                frag_start = i + 1
            i += 1
        tail = line[frag_start:]
        if tail.strip():
            results.append((tail, None))
        return results

    def render(self):
        self.collect()
        bare_star_index, bare_slash_index = self._scan_source_params()

        ind = self.indent
        lines = []
        prefix = "async def" if self.is_async else "def"
        lines.append(f"{ind}{prefix} {self.name}(")
        body_indent = ind + "    "

        # Build render slots: params in order, with separators inserted at
        # their recorded positions.
        slots = []
        for i, p in enumerate(self.params):
            slots.append(("param", p, i))
        # Insert separators in reverse so indices stay valid
        for idx in sorted([x for x in (bare_star_index, bare_slash_index)
                           if x is not None], reverse=True):
            kind = "*" if idx == bare_star_index else "/"
            slots.insert(idx, ("sep", kind, None))

        n = len(slots)
        for si, (kind, payload, pidx) in enumerate(slots):
            if kind == "sep":
                line = body_indent + payload
                if si < n - 1:
                    line += ","
                lines.append(line)
                continue
            p = payload
            for c in p.comments_before:
                lines.append(body_indent + c)
            line = body_indent + p.text
            if p.default is not None:
                line += f" = {p.default}"
            if si < n - 1:
                line += ","
            if p.inline_comment:
                line += f" {p.inline_comment}"
            lines.append(line)

        close = body_indent + ")"
        ret = self._return_annotation_text()
        if ret:
            close += f" -> {ret}"
        close += ":"
        lines.append(close)
        return "\n".join(lines)

    def _return_annotation_text(self):
        r = self.node.returns
        if r is None:
            return None
        seg = self._get_source_segment(r)
        if seg is None:
            return None
        return " ".join(seg.split())


def process_file(path, dry_run):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"SKIP syntax error {path}: {e}", file=sys.stderr)
        return 0

    seg_lines = source.splitlines(keepends=True)

    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            indent = " " * node.col_offset
            funcs.append(FuncSig(path, node, source, indent))

    # process bottom-up so line offsets stay valid
    funcs.sort(key=lambda f: f.lineno, reverse=True)
    changed = 0
    lines = seg_lines[:]
    for f in funcs:
        params = f.collect()
        if len(params) < 3:
            continue
        start = f.lineno - 1
        end = f._header_end_line()
        old = "".join(lines[start:end])
        new = f.render() + "\n"
        if old == new:
            continue
        lines[start:end] = [new]
        changed += 1
    if changed and not dry_run:
        new_source = "".join(lines)
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            print(f"ABORT {path}: reformatted source failed to parse: {e}", file=sys.stderr)
            return 0
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_source)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_files = 0
    total_funcs = 0
    for dirpath, dirnames, filenames in os.walk(TARGET_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            changed = process_file(path, args.dry_run)
            if changed:
                total_files += 1
                total_funcs += changed
                print(f"{path}: {changed} signature(s) reformatted")
    print(f"TOTAL: {total_files} files, {total_funcs} signatures")


if __name__ == "__main__":
    main()
