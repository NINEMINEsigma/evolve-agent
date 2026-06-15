"""
环境检查脚本 — 验证当前平台是否满足 llama.cpp 本地编译要求。

用法:
    python check_env.py                # 基本检查
    python check_env.py --cuda         # 包含 CUDA 检查
    python check_env.py --cuda --json  # JSON 格式输出

退出码:
    0 = 所有检查通过
    1 = 存在严重问题（无法编译）
    2 = 存在警告（可能编译，但某些特性不可用）
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── 项目根目录 ──
PROJECT_ROOT = Path(__file__).resolve().parent
THIRD_DIR = PROJECT_ROOT / "third"
LLAMA_APIS_DIR = THIRD_DIR / "llamaapis"
LLAMA_CPP_SRC = LLAMA_APIS_DIR / "lib" / "llama.cpp"
LLAMA_CPP_BUILD = LLAMA_CPP_SRC / "build"


# ── 检查结果模型 ──

@dataclass
class CheckResult:
    name: str
    status: str       # "pass" | "fail" | "warn"
    message: str = ""
    detail: str = ""


# ── 辅助函数 ──

def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    """执行命令，返回 (exit_code, stdout+stderr)"""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        output = (r.stdout or "") + (r.stderr or "")
        return r.returncode, output.strip()
    except FileNotFoundError:
        return -1, "command not found"
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _which(name: str) -> str | None:
    """return path if executable exists in PATH"""
    return shutil.which(name)


# ── 单项检查 ──

def check_platform() -> CheckResult:
    system = platform.system()
    machine = platform.machine()
    py_ver = sys.version
    is_64bit = sys.maxsize > 2**32

    detail = (
        f"OS: {system} {platform.release()} ({machine})\n"
        f"Python: {py_ver.split()[0]} ({'64-bit' if is_64bit else '32-bit'})\n"
        f"CPU cores: {os.cpu_count() or 'unknown'}"
    )

    if system not in ("Windows", "Linux", "Darwin"):
        return CheckResult("platform", "fail", f"不支持的操作系统: {system}", detail)
    if not is_64bit:
        return CheckResult("platform", "fail", "需要 64 位系统", detail)
    return CheckResult("platform", "pass", f"{system} {machine}", detail)


def check_cmake() -> CheckResult:
    path = _which("cmake")
    if not path:
        return CheckResult("cmake", "fail", "未找到 cmake，请安装 cmake 并加入 PATH")

    rc, out = _run(["cmake", "--version"])
    if rc != 0:
        return CheckResult("cmake", "fail", f"cmake 执行失败: {out}")
    first_line = out.splitlines()[0] if out else "unknown"
    # 提取版本号
    ver = first_line.replace("cmake version", "").strip()
    return CheckResult("cmake", "pass", f"cmake {ver}", first_line)


def check_compiler() -> CheckResult:
    system = platform.system()

    if system == "Windows":
        # 检查 MSVC (cl.exe) — 在 PATH 中即表示 VS 开发环境已激活
        cl_path = _which("cl")
        if cl_path:
            return CheckResult("compiler", "pass", f"MSVC found: {cl_path}")

        # 检查 vcvars 是否已加载 (VS 开发者命令行环境)
        if os.environ.get("VSCMD_VER"):
            return CheckResult("compiler", "pass", "Visual Studio 开发环境已激活")

        # 从 vswhere 检测 VS 安装（cmake 在 configure 阶段通过 VS Installer
        # COM 接口自动发现 VS，与 vswhere 使用相同的检测机制，所以 vswhere
        # 能找到即 cmake 也能找到）
        for pf_var in ("ProgramFiles", "ProgramFiles(x86)"):
            pf = os.environ.get(pf_var)
            if not pf:
                continue
            vswhere = Path(pf) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
            if vswhere.exists():
                rc, out = _run([str(vswhere), "-latest", "-property", "installationPath"])
                if rc == 0 and out.strip():
                    return CheckResult(
                        "compiler", "pass",
                        f"Visual Studio detected via vswhere: {out.strip()}",
                    )

        return CheckResult(
            "compiler", "fail",
            "未检测到 MSVC 编译器。请安装 Visual Studio Build Tools 或 Visual Studio，\n"
            "并确保从 'Developer Command Prompt for VS' 运行此脚本。\n"
            "下载: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        )

    elif system == "Linux":
        for cc in ("gcc", "clang"):
            path = _which(cc)
            if path:
                rc, out = _run([cc, "--version"])
                first = out.splitlines()[0] if out else "unknown"
                return CheckResult("compiler", "pass", f"{cc} at {path}", first)
        return CheckResult("compiler", "fail", "未找到 GCC 或 Clang，请安装 build-essential")

    elif system == "Darwin":
        path = _which("clang")
        if path:
            rc, out = _run(["clang", "--version"])
            first = out.splitlines()[0] if out else "unknown"
            return CheckResult("compiler", "pass", f"clang at {path}", first)
        # 检查 xcode-select
        rc, out = _run(["xcode-select", "-p"])
        if rc == 0:
            return CheckResult("compiler", "warn", "Xcode 已安装但未找到 clang 编译器")
        return CheckResult("compiler", "fail", "未找到编译器，请安装 Xcode Command Line Tools")

    return CheckResult("compiler", "fail", f"未适配平台: {system}")


def check_cuda() -> CheckResult:
    """仅在 --cuda 参数传入时调用"""
    nvsmi = _which("nvidia-smi")
    if not nvsmi:
        return CheckResult("cuda", "fail", "未找到 nvidia-smi，请安装 NVIDIA 驱动和 CUDA Toolkit")

    rc, out = _run([nvsmi, "--query-gpu=index,name,memory.total,driver_version",
                    "--format=csv,noheader"])
    if rc != 0:
        return CheckResult("cuda", "fail", f"nvidia-smi 执行失败: {out}")

    gpus = [line.strip() for line in out.splitlines() if line.strip()]
    if not gpus:
        return CheckResult("cuda", "fail", "nvidia-smi 未检测到 GPU")

    detail_lines = [f"GPU count: {len(gpus)}"]
    for g in gpus:
        detail_lines.append(f"  {g}")
    detail = "\n".join(detail_lines)

    # CUDA 版本
    nvcc = _which("nvcc")
    cuda_ver = "unknown"
    if nvcc:
        rc2, out2 = _run([nvcc, "--version"])
        if rc2 == 0:
            for line in out2.splitlines():
                if "release" in line:
                    cuda_ver = line.strip()
                    break
    else:
        # nvcc 不是必须的，cmake 可以通过 nvcc 检测 CUDA
        pass

    return CheckResult("cuda", "pass", f"已检测到 CUDA ({cuda_ver}), {len(gpus)} GPU(s)", detail)


def check_nvcc() -> CheckResult:
    """检查 nvcc（用于 CUDA 编译）"""
    nvcc = _which("nvcc")
    if not nvcc:
        # 如果是 Windows，检查常见 CUDA 安装路径
        if platform.system() == "Windows":
            cuda_path = os.environ.get("CUDA_PATH", "")
            if cuda_path:
                return CheckResult("nvcc", "warn",
                    f"CUDA_PATH 已设置 ({cuda_path})，但 nvcc 不在 PATH 中。"
                    "编译 cmake 时可能找不到 CUDA。建议将 %CUDA_PATH%/bin 加入 PATH。")
        return CheckResult("nvcc", "warn", "未找到 nvcc，cmake 可能无法自动检测 CUDA")

    rc, out = _run([nvcc, "--version"])
    first = out.splitlines()[0] if out else "unknown"
    # 提取 release 版本行
    ver_line = ""
    for line in out.splitlines():
        if "release" in line:
            ver_line = line.strip()
            break
    return CheckResult("nvcc", "pass", f"nvcc: {ver_line or first}", first)


def check_git() -> CheckResult:
    git = _which("git")
    if not git:
        return CheckResult("git", "fail", "未找到 git，请安装 git")

    rc, out = _run(["git", "--version"])
    ver = out.strip() if rc == 0 else "unknown"
    return CheckResult("git", "pass", f"git: {ver}")


def check_submodule_init() -> CheckResult:
    """检查 third/llamaapis 和 lib/llama.cpp 子模块是否已初始化"""
    issues: list[str] = []

    # third/llamaapis 本身是子模块
    gitmodules = PROJECT_ROOT / ".gitmodules"
    if not gitmodules.exists():
        return CheckResult("submodule", "fail", "未找到 .gitmodules 文件，是否在 git 仓库中？")

    # 检查 third/llamaapis 是否有内容
    if not (LLAMA_APIS_DIR / "system" / "builder.py").exists():
        issues.append("third/llamaapis 子模块未初始化或为空")

    # 检查 lib/llama.cpp 子模块
    if not (LLAMA_CPP_SRC / "CMakeLists.txt").exists():
        issues.append("lib/llama.cpp 子模块未初始化或为空")

    if issues:
        hint = (
            "请运行以下命令:\n"
            f"  cd {PROJECT_ROOT}\n"
            "  git submodule update --init --recursive"
        )
        return CheckResult("submodule", "fail", "; ".join(issues), hint)

    # 获取 submodule 状态
    rc, out = _run(["git", "submodule", "status", "--recursive"],
                   timeout=10)
    detail = out if rc == 0 else ""

    return CheckResult("submodule", "pass", "子模块已初始化", detail)


def check_llamacpp_build() -> CheckResult:
    """检查 llama.cpp 编译产物状态"""
    system = platform.system()

    # 确定二进制路径
    if system == "Windows":
        binary_rel = Path("bin") / "Release" / "llama-server.exe"
    else:
        binary_rel = Path("bin") / "llama-server"

    binary_path = LLAMA_CPP_BUILD / binary_rel
    build_dir = LLAMA_CPP_BUILD

    if not build_dir.exists():
        return CheckResult("llamacpp_build", "warn",
            "build 目录不存在，尚未编译。启动时 LlamaBuilder 会自动编译。",
            f"预期的编译输出目录: {build_dir}")

    # 检查 build 目录内容
    detail_lines = []
    build_size = _dir_size(build_dir)
    detail_lines.append(f"build 目录大小: {_fmt_size(build_size)}")

    built = binary_path.exists()
    if built:
        bin_size = binary_path.stat().st_size
        detail_lines.append(f"llama-server 大小: {_fmt_size(bin_size)}")
        return CheckResult("llamacpp_build", "pass",
            f"llama-server 已编译 ({_fmt_size(bin_size)})",
            "\n".join(detail_lines))
    else:
        detail_lines.append("llama-server 未找到")
        return CheckResult("llamacpp_build", "warn",
            "build 目录存在但 llama-server 未找到。下次启动时将自动重新编译。",
            "\n".join(detail_lines))


def check_llamacpp_source() -> CheckResult:
    """检查 llama.cpp 源码目录结构"""
    cmakelists = LLAMA_CPP_SRC / "CMakeLists.txt"
    if not cmakelists.exists():
        return CheckResult("llamacpp_source", "fail",
            f"未找到 {cmakelists}，子模块可能未初始化")

    # 简单检查关键目录
    has_gpu = (LLAMA_CPP_SRC / "ggml-cuda").exists()
    detail = f"路径: {LLAMA_CPP_SRC}\nCUDA backend: {'yes' if has_gpu else 'no'}"

    return CheckResult("llamacpp_source", "pass", f"源码目录存在 ({_dir_size(LLAMA_CPP_SRC)} 文件)", detail)


def check_disk_space() -> CheckResult:
    """检查编译所需磁盘空间"""
    root = PROJECT_ROOT
    try:
        usage = shutil.disk_usage(root)
        free_gb = usage.free / (1024**3)
        detail = f"剩余空间: {free_gb:.1f} GiB"
        if free_gb < 1:
            return CheckResult("disk_space", "warn",
                f"磁盘空间有限 ({free_gb:.1f} GiB)，编译可能需要更多空间", detail)
        return CheckResult("disk_space", "pass", f"磁盘空间充足 ({free_gb:.1f} GiB)", detail)
    except Exception as e:
        return CheckResult("disk_space", "warn", f"无法检查磁盘空间: {e}")


# ── 工具函数 ──

def _dir_size(path: Path) -> int:
    """估算目录中文件的总字节数（最多 5000 个文件）"""
    total = 0
    count = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                count += 1
                if count > 5000:
                    break
                total += f.stat().st_size
    except (PermissionError, OSError):
        pass
    return total


def _fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024**2:
        return f"{b/1024:.1f} KB"
    elif b < 1024**3:
        return f"{b/1024**2:.1f} MB"
    else:
        return f"{b/1024**3:.1f} GB"


def _check_llama_cpp_submodule_initialized() -> bool:
    return (LLAMA_CPP_SRC / "CMakeLists.txt").exists()


def _check_third_llamaapis_initialized() -> bool:
    return (LLAMA_APIS_DIR / "system" / "builder.py").exists()


# ── 主流程 ──

def main():
    parser = argparse.ArgumentParser(
        description="Evolve Agent 环境检查 — 验证 llama.cpp 编译环境",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python check_env.py                # 基本检查\n"
            "  python check_env.py --cuda         # 包含 CUDA 检查\n"
            "  python check_env.py --json         # JSON 输出\n"
            "\n"
            "退出码:\n"
            "  0 = 一切就绪\n"
            "  1 = 存在严重问题\n"
            "  2 = 存在警告\n"
        ),
    )
    parser.add_argument("--cuda", action="store_true", help="强制要求 CUDA，启用后将检查 nvidia-smi/nvcc")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    results: list[CheckResult] = []

    # ── 第 1 组：基础平台 ──
    results.append(check_platform())
    results.append(check_disk_space())

    # ── 第 2 组：构建工具 ──
    results.append(check_cmake())
    results.append(check_compiler())

    # ── 第 3 组：版本控制 ──
    results.append(check_git())
    results.append(check_submodule_init())

    # ── 第 4 组：llama.cpp 源码与构建状态 ──
    if _check_llama_cpp_submodule_initialized():
        results.append(check_llamacpp_source())
        results.append(check_llamacpp_build())

    # ── 第 5 组：CUDA（可选） ──
    if args.cuda:
        results.append(check_cuda())
        results.append(check_nvcc())

    # ── 汇总 ──
    passed = [r for r in results if r.status == "pass"]
    warned = [r for r in results if r.status == "warn"]
    failed = [r for r in results if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]

    # 确定最终退出码
    if failed:
        exit_code = 1
    elif warned:
        exit_code = 2
    else:
        exit_code = 0

    # ── 输出 ──
    if args.json:
        output = {
            "exit_code": exit_code,
            "checks": [
                {"name": r.name, "status": r.status, "message": r.message, "detail": r.detail}
                for r in results
            ],
            "summary": {
                "passed": len(passed),
                "warned": len(warned),
                "failed": len(failed),
                "skipped": len(skipped),
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # 人类可读输出
        print(f"{"=" * 60}\nEvolve Agent 环境检查报告\n")
        print(f"{'=' * 60}\n")

        tags = {"pass": "✅ PASS", "warn": "⚠️  WARN", "fail": "❌ FAIL", "skip": "⏭️  SKIP"}

        for r in results:
            tag = tags.get(r.status, r.status.upper())
            print(f"  [{tag}] {r.name}")
            print(f"         {r.message}")
            if r.detail:
                for line in r.detail.splitlines():
                    print(f"         {line}")
            print()

        # 摘要
        print(f"{'=' * 60}")
        print(f"  结果:  {len(passed)} pass, {len(warned)} warn, {len(failed)} fail, {len(skipped)} skip")
        print(f"  退出码: {exit_code}")

        if exit_code == 0:
            print(f"\n  ✅ 环境就绪，可以编译运行！")
        elif exit_code == 1:
            print(f"\n  ❌ 存在 {len(failed)} 个严重问题，请修复后重试。")
        else:
            print(f"\n  ⚠️  存在 {len(warned)} 个警告，大部分功能可用。")

        print(f"{'=' * 60}\n")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()