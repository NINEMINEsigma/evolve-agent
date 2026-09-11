#!/usr/bin/env python
"""Static validation for Evolve Agent Session Stage and Chat Style artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAX_CHAT_STYLE_BYTES = 256 * 1024
PUBLIC_SELECTORS = (
    'data-chat-scope',
    'data-message-role',
    'data-character-hovered',
)
FORBIDDEN_AT_RULES = ('@import', '@namespace', '@page', '@document')
GLOBAL_SELECTOR_RE = re.compile(r'(^|[,}\s])(?:html|body|:root)(?=[\s,{:#.\[])', re.I)


def ok(message: str) -> None:
    print(f'[ok]   {message}')


def warn(message: str) -> None:
    print(f'[warn] {message}')


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f'[fail] {message}')


def read_text(path: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        fail(errors, f'not UTF-8: {path}')
    except OSError as error:
        fail(errors, f'cannot read {path}: {error}')
    return None


def balanced(text: str, opening: str, closing: str) -> bool:
    depth = 0
    quote = None
    escaped = False
    in_comment = False
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if in_comment:
            if pair == '*/':
                in_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            char = text[i]
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if pair == '/*':
            in_comment = True
            i += 2
            continue
        char = text[i]
        if char in ('"', "'"):
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0 and quote is None and not in_comment


def validate_stage(target: Path, errors: list[str]) -> None:
    """Accept either a Stage directory (expects index.html) or a single HTML file."""
    if target.is_file():
        index = target
        stage_dir = target.parent
    elif target.is_dir():
        index = target / 'index.html'
        stage_dir = target
    else:
        fail(errors, f'path does not exist: {target}')
        return

    print(f'\nStage: {stage_dir}')
    print(f'entry: {index.name}')

    if not index.is_file():
        fail(errors, f'missing Stage entry: {index}')
        return
    ok('Stage entry exists')
    text = read_text(index, errors)
    if text is None:
        return

    if not re.search(r'<html\b[^>]*background\s*:\s*transparent', text, re.I | re.S):
        warn('html tag does not explicitly declare a transparent background')
    else:
        ok('html explicitly uses transparent background')
    if not re.search(r'<body\b[^>]*background\s*:\s*transparent', text, re.I | re.S):
        warn('body tag does not explicitly declare a transparent background')
    else:
        ok('body explicitly uses transparent background')
    if 'pointer-events: none' not in text:
        warn('Stage page does not explicitly disable pointer events')
    else:
        ok('Stage page disables pointer events')
    if not balanced(text, '{', '}'):
        fail(errors, 'unbalanced braces in Stage HTML/CSS/JS')
    else:
        ok('Stage braces are balanced')

    refs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', text, re.I)
    for ref in refs:
        if ref.startswith(('http://', 'https://', 'data:', '#', '/')):
            if ref.startswith(('http://', 'https://')):
                warn(f'external Stage resource: {ref}')
            continue
        target = (stage_dir / ref.split('?', 1)[0].split('#', 1)[0]).resolve()
        try:
            target.relative_to(stage_dir.resolve())
        except ValueError:
            fail(errors, f'resource escapes Stage directory: {ref}')
            continue
        if not target.exists():
            fail(errors, f'missing referenced Stage resource: {ref}')
        else:
            ok(f'resource exists: {ref}')

    model_json = list(stage_dir.rglob('*.model3.json'))
    if model_json:
        ok(f'found {len(model_json)} Live2D model3 file(s)')
        if not list(stage_dir.rglob('*.moc3')):
            fail(errors, 'Live2D model3 exists but no .moc3 was found')
        else:
            ok('Live2D .moc3 asset exists')


def validate_chat_style(path: Path, errors: list[str]) -> None:
    print(f'\nChat Style: {path}')
    if not path.is_file():
        fail(errors, f'missing Chat Style entry: {path}')
        return
    size = path.stat().st_size
    if size > MAX_CHAT_STYLE_BYTES:
        fail(errors, f'Chat Style exceeds 256 KiB: {size} bytes')
    else:
        ok(f'Chat Style size is valid: {size} bytes')
    text = read_text(path, errors)
    if text is None:
        return
    lower = text.lower()
    for rule in FORBIDDEN_AT_RULES:
        if rule in lower:
            fail(errors, f'forbidden at-rule: {rule}')
    if GLOBAL_SELECTOR_RE.search(_strip_comments(text)):
        fail(errors, 'global selector detected (:root/html/body)')
    else:
        ok('no obvious global selector escape')
    if '!important' in lower:
        warn('!important found; avoid using it to fight host styles')
    if not balanced(text, '{', '}'):
        fail(errors, 'unbalanced CSS braces/comments/quotes')
    else:
        ok('CSS braces/comments/quotes are balanced')
    if not any(selector in text for selector in PUBLIC_SELECTORS):
        warn('no public data-* selector found; internal classes may be unstable')
    else:
        ok('public chat selector contract is used')
    for family in re.findall(r'@font-face\s*\{(.*?)\}', text, re.I | re.S):
        match = re.search(r'font-family\s*:\s*["\']?([^;"\']+)', family, re.I)
        if not match or not match.group(1).strip().startswith('ChatStyle-'):
            fail(errors, '@font-face family must start with ChatStyle-')
    if 'backdrop-filter' in text:
        warn('backdrop-filter found; verify it is not duplicated on bubble and inner blocks')


def _strip_comments(text: str) -> str:
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Statistically validate Evolve Agent Session Stage / Chat Style artifacts.',
        epilog=(
            '--stage-dir accepts either a Stage directory (expects index.html) '
            'or a single Stage HTML file. --chat-style expects a CSS file.'
        ),
    )
    parser.add_argument(
        '--stage-dir',
        type=Path,
        help='Stage directory (expects index.html) or a single Stage HTML file',
    )
    parser.add_argument(
        '--chat-style',
        type=Path,
        help='Path to chat-style/index.css',
    )
    args = parser.parse_args()
    if not args.stage_dir and not args.chat_style:
        parser.error('provide --stage-dir and/or --chat-style')

    errors: list[str] = []
    if args.stage_dir:
        validate_stage(args.stage_dir.resolve(), errors)
    if args.chat_style:
        validate_chat_style(args.chat_style.resolve(), errors)

    print(f'\nResult: {len(errors)} error(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
