"""Read-only interpreter diagnostics used by the desktop launcher, without application imports."""

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import struct
import sys
import traceback


KEY_MODULES = (
    "pydantic", "fastapi", "httpx", "uvicorn", "openai", "anthropic",
    "watchdog", "pathspec",
)
TOOL_DISTRIBUTIONS = ("pip", "setuptools", "wheel", "pywinpty")
EXIT_CODES = {
    "DEPENDENCY_MISSING": 10,
    "PYTHON_VERSION_MISMATCH": 11,
    "PREFIX_MISMATCH": 12,
    "ARCHITECTURE_MISMATCH": 13,
    "PROBE_INTERNAL_ERROR": 70,
}


def canonical(value: str) -> str:
    return os.path.normcase(os.path.realpath(value))


def is_within(value: str, root: str) -> bool:
    value, root = canonical(value), canonical(root)
    if os.path.splitdrive(value)[0] != os.path.splitdrive(root)[0]:
        return False
    return os.path.commonpath((value, root)) == root


def diagnose(args: argparse.Namespace) -> str | None:
    version = sys.version_info[:3]
    if args.mode == "manual":
        if not (version >= (3, 12, 0) and version < (3, 13, 0)):
            return "PYTHON_VERSION_MISMATCH"
    elif platform.python_version() != args.expected_version:
        return "PYTHON_VERSION_MISMATCH"
    if struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        return "ARCHITECTURE_MISMATCH"
    if args.mode != "manual":
        if not args.expected_base_root:
            raise ValueError("Managed diagnostics require an expected base root")
        if not is_within(sys.base_prefix, args.expected_base_root):
            return "PREFIX_MISMATCH"
    if args.mode == "environment":
        if not args.expected_prefix:
            raise ValueError("Environment diagnostics require an expected prefix")
        if canonical(sys.prefix) != canonical(args.expected_prefix):
            return "PREFIX_MISMATCH"
        if not is_within(sys.executable, args.expected_prefix):
            return "PREFIX_MISMATCH"
    if args.mode == "base":
        if canonical(sys.prefix) != canonical(sys.base_prefix):
            return "PREFIX_MISMATCH"
        return None
    # 按固定诊断清单导入，不发现插件，也不导入项目或有桌面连接副作用的模块。
    for module_name in KEY_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if not error.name:
                raise
            print(f"Missing required module: {error.name}", file=sys.stderr)
            return "DEPENDENCY_MISSING"
    if args.mode == "environment":
        for distribution in TOOL_DISTRIBUTIONS:
            try:
                importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                print(f"Missing required distribution: {distribution}", file=sys.stderr)
                return "DEPENDENCY_MISSING"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("base", "environment", "manual"), required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-prefix")
    parser.add_argument("--expected-base-root")
    args = parser.parse_args()
    try:
        error_code = diagnose(args)
    except Exception:
        # 未知诊断异常必须区别于可恢复的环境失效。
        traceback.print_exc(file=sys.stderr)
        error_code = "PROBE_INTERNAL_ERROR"
    result = {
        "schemaVersion": 1,
        "mode": args.mode,
        "ok": error_code is None,
        "errorCode": error_code,
        "executable": os.path.abspath(sys.executable),
        "prefix": os.path.abspath(sys.prefix),
        "basePrefix": os.path.abspath(sys.base_prefix),
        "version": platform.python_version(),
        "architecture": struct.calcsize("P") * 8,
    }
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if error_code is None else EXIT_CODES[error_code]


if __name__ == "__main__":
    raise SystemExit(main())
