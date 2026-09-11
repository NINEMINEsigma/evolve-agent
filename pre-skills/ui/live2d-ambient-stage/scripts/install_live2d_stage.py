#!/usr/bin/env python
"""Deploy a Live2D ambient stage into a session stage directory.

The script copies the shared rendering libraries plus one model's runtime assets
from this skill into the target stage directory, then renders index.html from
templates/stage.template.html and templates/models/<model>.json.

Examples:
    python install_live2d_stage.py --list-models
    python install_live2d_stage.py --model mao_pro --stage-dir "D:/.../sessions/<id>/stage"
    python install_live2d_stage.py --model shizuku --stage-dir "..." --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_ROOT / "assets"
LIBS_DIR = ASSETS_DIR / "libs"
MODELS_DIR = ASSETS_DIR / "models"
TEMPLATE_PATH = SKILL_ROOT / "templates" / "stage.template.html"
CONFIG_DIR = SKILL_ROOT / "templates" / "models"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
BACKGROUND_CATALOG = SKILL_ROOT / "templates" / "backgrounds.json"

CONFIG_TOKEN = "/*__STAGE_CONFIG__*/"
DEFAULT_LICENSE_TEXT = (
    "This content uses sample data owned and copyrighted by Live2D Inc."
)
REQUIRED_LIBS = ("live2dcubismcore.min.js", "pixi.min.js", "cubism4.min.js")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy a Live2D ambient stage into a session stage directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", help="Model name; matches templates/models/<name>.json")
    parser.add_argument(
        "--stage-dir",
        help="Absolute path of the target stage directory (the folder holding index.html)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing index.html and asset files",
    )
    parser.add_argument(
        "--background",
        help=(
            "Optional background: a catalog id/label (e.g. room-interior) "
            "or an absolute path to an image file"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned operations without writing anything",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List model configs bundled with this skill and exit",
    )
    parser.add_argument(
        "--list-backgrounds",
        action="store_true",
        help="List bundled background presets and exit",
    )
    return parser


def list_models() -> int:
    if not CONFIG_DIR.is_dir():
        print(f"[error] missing config directory: {CONFIG_DIR}")
        return 1

    rows = []
    for path in sorted(CONFIG_DIR.glob("*.json")):
        name = path.stem
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            rows.append((name, "invalid config: %s" % error, "-", "-"))
            continue
        rows.append(
            (
                name,
                config.get("label", "-"),
                str(len(config.get("actions", []))),
                str(config.get("expressionCount", 0)),
            )
        )

    if not rows:
        print("[error] no model config found")
        return 1

    print("available models (name | label | actions | expressions)")
    for name, label, actions, expressions in rows:
        print(f"  {name:<12} | {label:<10} | {actions:>7} | {expressions:>11}")

    installed = sorted(p.name for p in MODELS_DIR.iterdir()) if MODELS_DIR.is_dir() else []
    print("\ninstalled model assets:", ", ".join(installed) if installed else "(none)")
    return 0


def load_background_catalog() -> list:
    if not BACKGROUND_CATALOG.is_file():
        return []
    try:
        data = json.loads(BACKGROUND_CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def list_backgrounds() -> int:
    catalog = load_background_catalog()
    if not catalog:
        print(f"[error] no background catalog found: {BACKGROUND_CATALOG}")
        return 1

    print("available backgrounds (id | label | file)")
    for entry in catalog:
        file_name = entry.get("file") or "(transparent)"
        print(
            f"  {entry.get('id', '-'):<22} | {entry.get('label', '-'):<10} | {file_name}"
        )

    missing = [
        entry["file"]
        for entry in catalog
        if entry.get("file") and not (BACKGROUNDS_DIR / entry["file"]).is_file()
    ]
    if missing:
        print("\n[warning] missing asset files: " + ", ".join(missing))
    return 0


def resolve_background(value: str) -> tuple:
    """Resolve --background to (source_path, file_name)."""
    key = value.strip()
    for entry in load_background_catalog():
        file_name = entry.get("file")
        if not file_name:
            continue
        if key in (entry.get("id"), entry.get("label"), file_name):
            path = BACKGROUNDS_DIR / file_name
            if not path.is_file():
                raise FileNotFoundError(f"background asset missing: {path}")
            return path, file_name

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError(
            f"unknown background preset: {value}; "
            "use --list-backgrounds or pass an absolute file path"
        )
    if not candidate.is_file():
        raise FileNotFoundError(f"background image not found: {candidate}")
    return candidate, candidate.name


def load_config(model: str) -> dict:
    config_path = CONFIG_DIR / f"{model}.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"missing model config: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("label", "modelUrl", "actions", "layout"):
        if key not in config:
            raise ValueError(f"model config missing required field: {key}")
    return config


def validate_model_assets(model: str) -> Path:
    model_dir = MODELS_DIR / model
    if not model_dir.is_dir():
        raise FileNotFoundError(f"missing model assets: {model_dir}")
    moc_files = list(model_dir.rglob("*.moc3"))
    model_json = list(model_dir.rglob("*.model3.json"))
    if not moc_files or not model_json:
        raise FileNotFoundError(
            f"model assets incomplete under {model_dir}: need .moc3 and .model3.json"
        )
    return model_dir


def copy_file(src: Path, dst: Path, force: bool, dry_run: bool) -> None:
    if dst.exists() and not force:
        print(f"  skip   {dst}")
        return
    action = "update" if dst.exists() else "copy  "
    print(f"  {action} {dst}")
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, force: bool, dry_run: bool) -> None:
    for item in sorted(src.rglob("*")):
        if item.is_dir():
            continue
        copy_file(item, dst / item.relative_to(src), force, dry_run)


def render_html(config: dict, template_text: str) -> str:
    payload = json.dumps(config, ensure_ascii=False, indent=2)
    html = template_text.replace(CONFIG_TOKEN, f"const CONFIG = {payload};")
    html = html.replace("__STAGE_TITLE__", f"{config['label']} Live2D Stage")
    html = html.replace(
        "__STAGE_ARIA__",
        f"随机待机的 Live2D 角色 {config['label']}",
    )
    html = html.replace("__LICENSE_TEXT__", DEFAULT_LICENSE_TEXT)
    return html


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_models:
        return list_models()

    if args.list_backgrounds:
        return list_backgrounds()

    if not args.model or not args.stage_dir:
        print("[error] --model and --stage-dir are required (or use --list-models)")
        return 2

    stage_dir = Path(args.stage_dir).expanduser()
    if not stage_dir.is_absolute():
        print(f"[error] --stage-dir must be an absolute path: {stage_dir}")
        return 2

    try:
        config = load_config(args.model)
        model_dir = validate_model_assets(args.model)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"[error] {error}")
        return 1

    if not LIBS_DIR.is_dir():
        print(f"[error] missing shared libs: {LIBS_DIR}")
        return 1

    missing_libs = [name for name in REQUIRED_LIBS if not (LIBS_DIR / name).is_file()]
    if missing_libs:
        print(f"[error] shared libs incomplete, missing: {', '.join(missing_libs)}")
        return 1

    index_path = stage_dir / "index.html"
    if index_path.exists() and not args.force:
        print(f"[error] {index_path} already exists; pass --force to overwrite")
        return 3

    background_src = None
    background_name = None
    background_url = None
    if args.background:
        try:
            background_src, background_name = resolve_background(args.background)
        except (FileNotFoundError, ValueError) as error:
            print(f"[error] {error}")
            return 1
        background_url = f"assets/backgrounds/{background_name}"

    print(f"skill root : {SKILL_ROOT}")
    print(f"model      : {args.model} ({config['label']})")
    print(f"stage dir  : {stage_dir}")
    print(f"background : {background_url or '(none)'}")
    print("plan:")
    copy_tree(LIBS_DIR, stage_dir / "assets" / "libs", args.force, args.dry_run)
    copy_tree(model_dir, stage_dir / "assets" / "models" / args.model, args.force, args.dry_run)

    license_src = ASSETS_DIR / "LICENSE-Live2D.md"
    if license_src.is_file():
        copy_file(license_src, stage_dir / "assets" / "LICENSE-Live2D.md", args.force, args.dry_run)

    if background_src is not None:
        copy_file(
            background_src,
            stage_dir / "assets" / "backgrounds" / background_name,
            args.force,
            args.dry_run,
        )

    print(f"  render {index_path}")
    if args.dry_run:
        print("\ndry run complete, nothing written")
        return 0

    stage_dir.mkdir(parents=True, exist_ok=True)
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    render_config = dict(config)
    render_config["background"] = background_url
    index_path.write_text(render_html(render_config, template_text), encoding="utf-8")

    print("\ndone. verify:")
    print(f"  {index_path}")
    print(f"  {stage_dir / 'assets' / 'libs'}")
    print(f"  {stage_dir / 'assets' / 'models' / args.model}")
    print("serve as: /files/ws/sessions/<session_id>/stage/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
