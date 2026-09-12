"""路径沙盒 — 固定命名空间安全边界与全局动态空间注册表。

所有文件系统工具和子进程调用必须通过此模块路由。LLM 可见路径使用
``namespace:relative/path`` 逻辑形式；真实绝对路径只在 Sandbox 内解析。

固定命名空间由 ``Namespace``、``_PERMISSIONS`` 与
``_static_namespace_bases()`` 定义。fast 模式还会从工作空间根目录的独立
easysave 文件加载全局动态沙盒空间；这些空间由 Application 持有的唯一
Sandbox 实例管理，并由 fast 模式下所有 Agent 共享。fallback 模式既不加载
也不启用动态空间。

动态空间的 ``is_readonly`` 与现有 ``third:``/``custom_*:`` 一样，只是
Sandbox 文件 API 层的逻辑只读，不是操作系统 ACL；外部 Shell、Python 和
后台进程不具备强制只读隔离。

不存在 ``self:`` 命名空间。所有路径必须携带显式前缀；裸路径、``..``
遍历和绝对路径均拒绝。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec
import tempfile
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from easysave import contains, load, save
from entity.typeref import make_config
from entity.constant import (
    DYNAMIC_SANDBOX_SPACE_DESCRIPTION_MAX_CHARS,
    DYNAMIC_SANDBOX_SPACE_NAME_PATTERN,
    DYNAMIC_SANDBOX_SPACES_ES_FILENAME,
    DYNAMIC_SANDBOX_SPACES_ES_KEY,
    NAMESPACE_PREFIXES,
    Namespace,
    SEARCH_PROCESS_STDERR_MAX_BYTES,
)
from entity.puretype import (
    DynamicSandboxSpace,
    DynamicSandboxSpaceData,
    ProcessLineStreamResult,
)
from system.atomic_io import replace_atomic
from system.context import get_runtime_context
from system.pathutils import find_repo_root
from system.text_codec import decode_text

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from system.subprocess_utils import SubprocessRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 权限模型
# ---------------------------------------------------------------------------


class Access(str, Enum):
    READ = "read"
    WRITE = "write"


# 映射：(mode, namespace) → 允许的访问类型
# "fast" 模式：fork=rw, ws=rw, skills=rw；third/custom_*=ro（只读）
# "fallback" 模式：fix=rw, ws=rw, skills=rw；third/custom_*=ro（只读）
# 不存在 self: 命名空间 — agent 不能查看或修改自身的运行时副本。
# 进化完全通过 fork:/fix: 实现。
_PERMISSIONS: dict[str, dict[str, list[Access]]] = {
    "fast": {
        Namespace.FORK.value:   [Access.READ, Access.WRITE],
        Namespace.WS.value:     [Access.READ, Access.WRITE],
        Namespace.SKILLS.value: [Access.READ, Access.WRITE],
        # 第一批只读命名空间 — 映射项目根目录，agent 可读不可写
        Namespace.THIRD.value:              [Access.READ],
        Namespace.CUSTOM_HOOKS.value:      [Access.READ],
        Namespace.CUSTOM_LLM_CLIENT.value: [Access.READ],
        Namespace.CUSTOM_TOOLS.value:      [Access.READ],
    },
    "fallback": {
        Namespace.FIX.value:    [Access.READ, Access.WRITE],
        Namespace.WS.value:     [Access.READ, Access.WRITE],
        Namespace.SKILLS.value: [Access.READ, Access.WRITE],
        # 第一批只读命名空间 — 与 fast 模式一致，仅可读
        Namespace.THIRD.value:              [Access.READ],
        Namespace.CUSTOM_HOOKS.value:      [Access.READ],
        Namespace.CUSTOM_LLM_CLIENT.value: [Access.READ],
        Namespace.CUSTOM_TOOLS.value:      [Access.READ],
    },
}


class SandboxError(PermissionError):
    """当工具操作违反沙盒约束时抛出。"""


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class ResolvedPath(BaseModel):
    """逻辑路径通过沙盒解析后的结果。"""

    model_config = ConfigDict(frozen=True)

    logical: str   # 例如 "ws:data/config.json"
    real: Path      # 磁盘上的绝对路径
    namespace: str  # 不带冒号的内置或动态命名空间名


class Sandbox:
    """Application 持有的路径安全边界与动态空间管理单例。"""

    def __init__(
        self,
        ctx: RuntimeContext,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._ctx: RuntimeContext = ctx
        self._runner: SubprocessRunner | None = runner
        self._dynamic_spaces_path: Path = (
            self._ctx.workspace / DYNAMIC_SANDBOX_SPACES_ES_FILENAME
        )
        self._dynamic_spaces_lock: threading.RLock = threading.RLock()
        self._dynamic_space_availability: dict[str, bool] = {}
        if self._ctx.mode == "fast":
            with self._dynamic_spaces_lock:
                self._dynamic_spaces_data = self._load_dynamic_spaces_unlocked()
                for space in self._dynamic_spaces_data.spaces:
                    available = self._is_dynamic_space_available_unlocked(space)
                    logger.info(
                        "Dynamic sandbox space loaded | name=%s path=%s readonly=%s available=%s",
                        space.name,
                        space.path,
                        space.is_readonly,
                        available,
                    )
        else:
            # fallback 模式不读取、不校验也不启用 fast 的动态空间配置。
            self._dynamic_spaces_data = DynamicSandboxSpaceData()

    def _get_runner(self) -> SubprocessRunner:
        """返回注入的 runner，或惰性获取 Application 全局单例。"""
        if self._runner is not None:
            return self._runner
        from system.application import Application
        return Application.current().subprocess_runner

    # -- 动态空间持久化与校验 --------------------------------------

    def _static_namespace_bases(self) -> dict[str, Path]:
        """返回当前模式全部内置命名空间的 base 映射。"""
        repo_root = find_repo_root()
        return {
            ns: base for ns, base in {
                Namespace.FORK.value: self._ctx.fork_path,
                Namespace.WS.value: self._ctx.agentspace,
                Namespace.FIX.value: self._ctx.fix_path,
                Namespace.SKILLS.value: repo_root / Namespace.SKILLS.value,
                Namespace.THIRD.value: repo_root / Namespace.THIRD.value,
                Namespace.CUSTOM_HOOKS.value: repo_root / Namespace.CUSTOM_HOOKS.value,
                Namespace.CUSTOM_LLM_CLIENT.value: repo_root / Namespace.CUSTOM_LLM_CLIENT.value,
                Namespace.CUSTOM_TOOLS.value: repo_root / Namespace.CUSTOM_TOOLS.value,
            }.items()
            if base is not None and ns in _PERMISSIONS.get(self._ctx.mode, {})
        }

    def _normalize_dynamic_path(self, raw_path: str) -> Path:
        """词法规范化绝对路径，不主动解析符号链接或目录联接点。"""
        if type(raw_path) is not str or not raw_path.strip():
            raise ValueError("Dynamic sandbox space path must be a non-empty string")
        candidate = Path(raw_path.strip())
        if not candidate.is_absolute():
            raise ValueError("Dynamic sandbox space path must be absolute")
        return Path(os.path.abspath(os.path.normpath(str(candidate))))

    @staticmethod
    def _path_compare_key(path: Path) -> str:
        """返回适合当前平台比较的规范路径键。"""
        return os.path.normcase(os.path.normpath(str(path)))

    def _paths_overlap(self, left: Path, right: Path) -> bool:
        """判断两个路径是否相同或存在父子包含关系。"""
        left_key = self._path_compare_key(left)
        right_key = self._path_compare_key(right)
        try:
            common = os.path.commonpath([left_key, right_key])
        except ValueError:
            return False
        return common == left_key or common == right_key

    def _validate_dynamic_space(
        self,
        space: DynamicSandboxSpace,
        *,
        existing: list[DynamicSandboxSpace],
        require_normalized: bool,
    ) -> DynamicSandboxSpace:
        """校验并返回规范化动态空间，不修改传入对象。"""
        if not isinstance(space, DynamicSandboxSpace):
            raise TypeError("Dynamic sandbox spaces must contain DynamicSandboxSpace instances")
        if set(space.__dict__) - {"name", "path", "description", "is_readonly"}:
            raise TypeError("DynamicSandboxSpace contains unknown fields")
        if type(space.name) is not str:
            raise TypeError("DynamicSandboxSpace.name must be a string")
        if type(space.path) is not str:
            raise TypeError("DynamicSandboxSpace.path must be a string")
        if type(space.description) is not str:
            raise TypeError("DynamicSandboxSpace.description must be a string")
        if type(space.is_readonly) is not bool:
            raise TypeError("DynamicSandboxSpace.is_readonly must be a boolean")

        name = space.name.strip()
        if not re.fullmatch(DYNAMIC_SANDBOX_SPACE_NAME_PATTERN, name):
            raise ValueError(
                "Dynamic sandbox space name must start with an ASCII letter or underscore "
                "and contain only ASCII letters, digits, and underscores"
            )
        if name in NAMESPACE_PREFIXES:
            raise ValueError(f"Dynamic sandbox space name conflicts with built-in namespace: {name!r}")

        description = space.description.strip()
        if not description:
            raise ValueError("Dynamic sandbox space description must not be empty")
        if len(description) > DYNAMIC_SANDBOX_SPACE_DESCRIPTION_MAX_CHARS:
            raise ValueError(
                "Dynamic sandbox space description exceeds "
                f"{DYNAMIC_SANDBOX_SPACE_DESCRIPTION_MAX_CHARS} characters"
            )
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in description):
            raise ValueError("Dynamic sandbox space description contains unsafe control characters")

        normalized_path = self._normalize_dynamic_path(space.path)
        normalized = DynamicSandboxSpace(
            name=name,
            path=str(normalized_path),
            description=description,
            is_readonly=space.is_readonly,
        )
        if require_normalized and (
            space.name != normalized.name
            or space.path != normalized.path
            or space.description != normalized.description
        ):
            raise ValueError(f"Dynamic sandbox space {space.name!r} is not normalized")

        for other in existing:
            if other.name == normalized.name:
                raise ValueError(f"Duplicate dynamic sandbox space name: {normalized.name!r}")
            if self._paths_overlap(normalized_path, Path(other.path)):
                raise ValueError(
                    f"Dynamic sandbox space path overlaps {other.name!r}: {other.path}"
                )
        for namespace, base in self._static_namespace_bases().items():
            if self._paths_overlap(normalized_path, base):
                raise ValueError(
                    f"Dynamic sandbox space path overlaps built-in namespace "
                    f"'{namespace}:': {base}"
                )
        return normalized

    def _load_dynamic_spaces_unlocked(self) -> DynamicSandboxSpaceData:
        """严格加载并校验 fast 模式动态空间根对象。"""
        config = make_config(self._dynamic_spaces_path)
        if not self._dynamic_spaces_path.exists():
            return DynamicSandboxSpaceData()
        if not contains(DYNAMIC_SANDBOX_SPACES_ES_KEY, config):
            raise TypeError(
                f"Dynamic sandbox space storage is missing key "
                f"{DYNAMIC_SANDBOX_SPACES_ES_KEY!r}"
            )
        data = load(
            DYNAMIC_SANDBOX_SPACES_ES_KEY,
            config,
            ignore_missing_fields=False,
        )
        if not isinstance(data, DynamicSandboxSpaceData):
            raise TypeError(
                "Dynamic sandbox space storage root must be DynamicSandboxSpaceData"
            )
        if set(data.__dict__) - {"spaces"}:
            raise TypeError("DynamicSandboxSpaceData contains unknown fields")
        if not isinstance(data.spaces, list):
            raise TypeError("DynamicSandboxSpaceData.spaces must be a list")
        validated: list[DynamicSandboxSpace] = []
        for space in data.spaces:
            validated.append(self._validate_dynamic_space(
                space,
                existing=validated,
                require_normalized=True,
            ))
        return DynamicSandboxSpaceData(spaces=validated)

    def _save_dynamic_spaces_unlocked(self) -> None:
        """将动态空间根对象写入同目录临时文件后原子替换。"""
        self._ctx.workspace.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self._dynamic_spaces_path.name}.",
            suffix=".tmp",
            dir=str(self._ctx.workspace),
            text=True,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text("{}", encoding="utf-8")
            save(
                DYNAMIC_SANDBOX_SPACES_ES_KEY,
                make_config(temp_path),
                self._dynamic_spaces_data,
            )
            replace_atomic(temp_path, self._dynamic_spaces_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _dynamic_space_by_name_unlocked(self, name: str) -> DynamicSandboxSpace | None:
        for space in self._dynamic_spaces_data.spaces:
            if space.name == name:
                return space
        return None

    @staticmethod
    def _dynamic_accesses(space: DynamicSandboxSpace) -> list[Access]:
        return [Access.READ] if space.is_readonly else [Access.READ, Access.WRITE]

    def _is_dynamic_space_available_unlocked(self, space: DynamicSandboxSpace) -> bool:
        available = Path(space.path).is_dir()
        previous = self._dynamic_space_availability.get(space.name)
        self._dynamic_space_availability[space.name] = available
        if previous is not None and previous != available:
            logger.warning(
                "Dynamic sandbox space availability changed | name=%s path=%s available=%s",
                space.name,
                space.path,
                available,
            )
        return available

    # -- 动态空间公共管理接口 --------------------------------------

    def list_dynamic_spaces(self) -> list[DynamicSandboxSpace]:
        """返回动态空间配置的深拷贝；fallback 模式返回空列表。"""
        if self._ctx.mode != "fast":
            return []
        with self._dynamic_spaces_lock:
            return [space.model_copy(deep=True) for space in self._dynamic_spaces_data.spaces]

    def list_dynamic_spaces_with_availability(
        self,
    ) -> list[tuple[DynamicSandboxSpace, bool]]:
        """返回动态空间配置拷贝及实时目录可用性。"""
        if self._ctx.mode != "fast":
            return []
        with self._dynamic_spaces_lock:
            return [
                (space.model_copy(deep=True), self._is_dynamic_space_available_unlocked(space))
                for space in self._dynamic_spaces_data.spaces
            ]

    def normalize_dynamic_space_path(self, raw_path: str) -> str:
        """返回动态空间路径的规范绝对字符串。"""
        return str(self._normalize_dynamic_path(raw_path))

    def add_dynamic_space(
        self,
        *,
        name: str,
        path: str,
        description: str,
        is_readonly: bool,
        session_id: str = "",
    ) -> tuple[DynamicSandboxSpace, bool]:
        """新增全局动态空间；完全相同的同名配置幂等成功。"""
        if self._ctx.mode != "fast":
            raise SandboxError("Dynamic sandbox spaces can only be modified in fast mode")
        if type(name) is not str:
            raise TypeError("Dynamic sandbox space name must be a string")
        if type(path) is not str:
            raise TypeError("Dynamic sandbox space path must be a string")
        if type(description) is not str:
            raise TypeError("Dynamic sandbox space description must be a string")
        if type(is_readonly) is not bool:
            raise TypeError("Dynamic sandbox space is_readonly must be a boolean")
        candidate = DynamicSandboxSpace(
            name=name,
            path=path,
            description=description,
            is_readonly=is_readonly,
        )
        with self._dynamic_spaces_lock:
            current = self._dynamic_space_by_name_unlocked(name.strip())
            others = [space for space in self._dynamic_spaces_data.spaces if space is not current]
            normalized = self._validate_dynamic_space(
                candidate,
                existing=others,
                require_normalized=False,
            )
            if current is not None:
                if current == normalized:
                    logger.info(
                        "Dynamic sandbox space add idempotent | session=%s name=%s path=%s",
                        session_id,
                        current.name,
                        current.path,
                    )
                    return current.model_copy(deep=True), False
                raise ValueError(
                    f"Dynamic sandbox space {normalized.name!r} already exists with different configuration"
                )
            self._dynamic_spaces_data.spaces.append(normalized)
            try:
                self._save_dynamic_spaces_unlocked()
            except BaseException:
                self._dynamic_spaces_data.spaces.pop()
                raise
            available = self._is_dynamic_space_available_unlocked(normalized)
            logger.info(
                "Dynamic sandbox space added | session=%s name=%s path=%s readonly=%s available=%s",
                session_id,
                normalized.name,
                normalized.path,
                normalized.is_readonly,
                available,
            )
            return normalized.model_copy(deep=True), True

    def update_dynamic_space(
        self,
        name: str,
        *,
        path: str,
        description: str,
        is_readonly: bool,
        session_id: str = "",
    ) -> DynamicSandboxSpace:
        """原子更新全局动态空间；名称固定不变。"""
        if self._ctx.mode != "fast":
            raise SandboxError("Dynamic sandbox spaces can only be modified in fast mode")
        if type(name) is not str:
            raise TypeError("Dynamic sandbox space name must be a string")
        if type(path) is not str:
            raise TypeError("Dynamic sandbox space path must be a string")
        if type(description) is not str:
            raise TypeError("Dynamic sandbox space description must be a string")
        if type(is_readonly) is not bool:
            raise TypeError("Dynamic sandbox space is_readonly must be a boolean")
        normalized_name = name.strip()
        if not re.fullmatch(DYNAMIC_SANDBOX_SPACE_NAME_PATTERN, normalized_name):
            raise ValueError("Invalid dynamic sandbox space name")
        if normalized_name in NAMESPACE_PREFIXES:
            raise ValueError("Built-in namespaces cannot be updated")
        candidate = DynamicSandboxSpace(
            name=normalized_name,
            path=path,
            description=description,
            is_readonly=is_readonly,
        )
        with self._dynamic_spaces_lock:
            current = self._dynamic_space_by_name_unlocked(normalized_name)
            if current is None:
                raise KeyError(f"Dynamic sandbox space not found: {normalized_name!r}")
            index = self._dynamic_spaces_data.spaces.index(current)
            others = [space for space in self._dynamic_spaces_data.spaces if space is not current]
            normalized = self._validate_dynamic_space(
                candidate,
                existing=others,
                require_normalized=False,
            )
            previous_availability = self._dynamic_space_availability.get(normalized_name)
            self._dynamic_spaces_data.spaces[index] = normalized
            try:
                self._save_dynamic_spaces_unlocked()
            except BaseException:
                self._dynamic_spaces_data.spaces[index] = current
                if previous_availability is None:
                    self._dynamic_space_availability.pop(normalized_name, None)
                else:
                    self._dynamic_space_availability[normalized_name] = previous_availability
                raise
            available = self._is_dynamic_space_available_unlocked(normalized)
            logger.info(
                "Dynamic sandbox space updated | session=%s name=%s path=%s readonly=%s available=%s",
                session_id,
                normalized.name,
                normalized.path,
                normalized.is_readonly,
                available,
            )
            return normalized.model_copy(deep=True)

    def remove_dynamic_space(self, name: str, *, session_id: str = "") -> bool:
        """按名称删除全局动态空间；名称不存在时幂等成功。"""
        if self._ctx.mode != "fast":
            raise SandboxError("Dynamic sandbox spaces can only be modified in fast mode")
        if type(name) is not str:
            raise TypeError("Dynamic sandbox space name must be a string")
        normalized_name = name.strip()
        if not re.fullmatch(DYNAMIC_SANDBOX_SPACE_NAME_PATTERN, normalized_name):
            raise ValueError("Invalid dynamic sandbox space name")
        if normalized_name in NAMESPACE_PREFIXES:
            raise ValueError("Built-in namespaces cannot be removed")
        with self._dynamic_spaces_lock:
            current = self._dynamic_space_by_name_unlocked(normalized_name)
            if current is None:
                logger.info(
                    "Dynamic sandbox space remove idempotent | session=%s name=%s",
                    session_id,
                    normalized_name,
                )
                return False
            index = self._dynamic_spaces_data.spaces.index(current)
            self._dynamic_spaces_data.spaces.pop(index)
            try:
                self._save_dynamic_spaces_unlocked()
            except BaseException:
                self._dynamic_spaces_data.spaces.insert(index, current)
                raise
            self._dynamic_space_availability.pop(current.name, None)
            logger.info(
                "Dynamic sandbox space removed | session=%s name=%s path=%s readonly=%s",
                session_id,
                current.name,
                current.path,
                current.is_readonly,
            )
            return True

    def is_namespaced_path(self, path: str) -> bool:
        """识别内置前缀及 fast 模式全部已配置动态前缀。"""
        if not isinstance(path, str) or ":" not in path:
            return False
        namespace = path.split(":", 1)[0]
        if namespace in _PERMISSIONS.get(self._ctx.mode, {}):
            return True
        if self._ctx.mode != "fast":
            return False
        with self._dynamic_spaces_lock:
            return self._dynamic_space_by_name_unlocked(namespace) is not None

    # -- 路径解析 ----------------------------------------------------

    def resolve(self, logical: str, access: Access) -> ResolvedPath:
        """解析固定或 fast 动态逻辑路径，检查权限并返回真实路径。"""
        if not logical or not isinstance(logical, str):
            raise SandboxError("logical path must be a non-empty string")

        if ":" not in logical:
            raise SandboxError(
                f"Path must carry a namespace prefix. Got: {logical!r}"
            )
        ns, rest = logical.split(":", 1)
        ns = ns.strip()

        static_bases = self._static_namespace_bases()
        base = static_bases.get(ns)
        allowed = _PERMISSIONS.get(self._ctx.mode, {}).get(ns)
        if base is None or allowed is None:
            dynamic_space: DynamicSandboxSpace | None = None
            if self._ctx.mode == "fast":
                with self._dynamic_spaces_lock:
                    dynamic_space = self._dynamic_space_by_name_unlocked(ns)
                    if dynamic_space is not None:
                        if not self._is_dynamic_space_available_unlocked(dynamic_space):
                            raise SandboxError(
                                f"Dynamic namespace '{ns}:' is currently unavailable; "
                                f"directory does not exist: {dynamic_space.path}"
                            )
                        dynamic_space = dynamic_space.model_copy(deep=True)
            if dynamic_space is None:
                available_names = list(static_bases)
                if self._ctx.mode == "fast":
                    with self._dynamic_spaces_lock:
                        available_names.extend(
                            space.name for space in self._dynamic_spaces_data.spaces
                        )
                raise SandboxError(
                    f"Unknown namespace '{ns}:' in mode '{self._ctx.mode}'. "
                    f"Allowed: {available_names}"
                )
            base = Path(dynamic_space.path)
            allowed = self._dynamic_accesses(dynamic_space)

        rest = rest.lstrip("/")
        if ".." in rest.split("/") or rest.startswith("/") or (len(rest) > 1 and rest[1] == ":"):
            raise SandboxError(f"Path traversal rejected: {logical!r}")
        if ".." in rest.split("\\") or rest.startswith("\\") or (len(rest) > 1 and rest[1] == ":"):
            raise SandboxError(f"Path traversal rejected: {logical!r}")

        real = (base / rest).resolve()
        try:
            real.relative_to(base)
        except ValueError:
            raise SandboxError(
                f"Resolved path {real} escapes namespace base {base}"
            )

        if access not in allowed:
            raise SandboxError(
                f"Access {access.value} denied for namespace '{ns}:' "
                f"in mode '{self._ctx.mode}'. Allowed: "
                f"{[item.value for item in allowed]}"
            )
        return ResolvedPath(logical=logical, real=real, namespace=ns)

    @property
    def agentspace(self) -> Path:
        """返回当前沙盒的 ws: 命名空间根目录。"""
        return self._ctx.agentspace

    def resolve_read(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.READ)

    def resolve_write(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.WRITE)

    def namespace_bases(self) -> dict[str, Path]:
        """返回当前可用命名空间 base；不存在的动态目录有意排除。"""
        bases = self._static_namespace_bases()
        if self._ctx.mode != "fast":
            return bases
        with self._dynamic_spaces_lock:
            for space in self._dynamic_spaces_data.spaces:
                if self._is_dynamic_space_available_unlocked(space):
                    bases[space.name] = Path(space.path)
        return bases

    def get_base(self, ns: Namespace) -> Path:
        """返回指定命名空间的物理根目录。

        供需要物理路径的外部消费者（importlib 注册、工具发现等）使用，
        而非沙盒文件操作。调用方应通过 ``Application.current().sandbox``
        或等价途径获取 Sandbox 实例。
        """
        base: Path | None = self.namespace_bases().get(ns.value)
        if base is None:
            raise SandboxError(
                f"Namespace '{ns.value}:' is not available in mode '{self._ctx.mode}'"
            )
        return base

    # -- 子进程（同样受沙盒约束） ----------------------------------------

    def run(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> subprocess.CompletedProcess:
        """以沙盒化工作目录运行子进程（同步，委托 SubprocessRunner）。

        保留命名空间校验与 cwd 解析层；子进程执行委托给 runner。

        *cwd_ns* — 子进程的逻辑工作目录。
        *timeout* — 超时秒数；``None`` 时从 ``RuntimeContext.tool_timeout`` 获取。
        *session_id* — 发起会话 ID，用于中断路径按会话终止活动进程。
        """
        if timeout is None:
            timeout = get_runtime_context().tool_timeout

        if not args:
            raise SandboxError("subprocess args must not be empty")

        # -- 验证 cwd --
        cwd_r: ResolvedPath = self.resolve(cwd_ns, Access.READ)
        if not cwd_r.real.is_dir():
            raise SandboxError(f"cwd does not exist or is not a directory: {cwd_ns}")

        # -- 验证任何看起来像逻辑路径的参数 --
        for arg in args:
            if ":" in arg and self.is_namespaced_path(arg):
                raise SandboxError(
                    f"Path arguments to subprocess commands must be resolved "
                    f"by the tool handler before calling sandbox.run(). "
                    f"Got: {arg!r}"
                )

        return self._get_runner().run(
            args, cwd=str(cwd_r.real), timeout=timeout,
            extra_env=extra_env, session_id=session_id,
        )

    async def run_async(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> subprocess.CompletedProcess:
        """以沙盒化工作目录运行子进程（真异步，事件循环不阻塞）。

        与 ``run()`` 同样的命名空间校验与 cwd 解析，但子进程执行为
        ``asyncio.create_subprocess_exec`` 协程挂起，事件循环保持响应。
        """
        if timeout is None:
            timeout = get_runtime_context().tool_timeout

        if not args:
            raise SandboxError("subprocess args must not be empty")

        # -- 验证 cwd --
        cwd_r: ResolvedPath = self.resolve(cwd_ns, Access.READ)
        if not cwd_r.real.is_dir():
            raise SandboxError(f"cwd does not exist or is not a directory: {cwd_ns}")

        # -- 验证任何看起来像逻辑路径的参数 --
        for arg in args:
            if ":" in arg and self.is_namespaced_path(arg):
                raise SandboxError(
                    f"Path arguments to subprocess commands must be resolved "
                    f"by the tool handler before calling sandbox.run(). "
                    f"Got: {arg!r}"
                )

        return await self._get_runner().run_async(
            args, cwd=str(cwd_r.real), timeout=timeout,
            extra_env=extra_env, session_id=session_id,
        )

    async def run_async_line_processor(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        on_stdout_line: Callable[[bytes], bool],
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
        stderr_byte_limit: int = SEARCH_PROCESS_STDERR_MAX_BYTES,
    ) -> ProcessLineStreamResult:
        """以沙盒化工作目录逐行消费子进程 stdout。

        保留与 ``run_async()`` 一致的 cwd 解析和逻辑路径参数拒绝逻辑，
        实际逐行执行委托给 ``SubprocessRunner``。
        """
        if timeout is None:
            timeout = get_runtime_context().tool_timeout

        if not args:
            raise SandboxError("subprocess args must not be empty")

        cwd_r: ResolvedPath = self.resolve(cwd_ns, Access.READ)
        if not cwd_r.real.is_dir():
            raise SandboxError(f"cwd does not exist or is not a directory: {cwd_ns}")

        for arg in args:
            if ":" in arg and self.is_namespaced_path(arg):
                raise SandboxError(
                    f"Path arguments to subprocess commands must be resolved "
                    f"by the tool handler before calling sandbox.run_async_line_processor(). "
                    f"Got: {arg!r}"
                )

        return await self._get_runner().run_async_line_processor(
            args,
            cwd=str(cwd_r.real),
            on_stdout_line=on_stdout_line,
            timeout=timeout,
            extra_env=extra_env,
            session_id=session_id,
            stderr_byte_limit=stderr_byte_limit,
        )

    def kill_active(self, session_id: str) -> None:
        """终止指定 session 登记的所有活动子进程树（委托 SubprocessRunner）。"""
        self._get_runner().kill_active(session_id)

    # -- 工具辅助方法 --------------------------------------------------

    def read(
        self,
        logical: str,
        offset: int = 0,
        limit: int = 100,
        *,
        strict_utf8: bool = False,
    ) -> str:
        """通过沙盒读取文件内容，支持按行分页和常见编码自动探测。

        普通查看路径会按候选编码严格尝试，避免日志中的单个非法 UTF-8
        字节导致整个 Read 失败。编辑路径应传入 ``strict_utf8=True``，
        防止非 UTF-8 文件被读取后又以 UTF-8 写回。
        """
        r: ResolvedPath = self.resolve_read(logical)
        try:
            raw = r.real.read_bytes()
            content, encoding, fallback_used = decode_text(
                raw, strict_utf8=strict_utf8,
            )
            if fallback_used:
                logger.warning(
                    "Sandbox.read decoded non-UTF-8 text | path=%s | encoding=%s",
                    logical,
                    encoding,
                )
            if limit > 0 and (offset > 0 or limit < len(content.splitlines())):
                lines: list[str] = content.splitlines()
                chunk: list[str] = lines[offset:offset + limit]
                return "\n".join(chunk)
            return content
        except FileNotFoundError:
            raise SandboxError(f"File not found: {logical}")
        except UnicodeDecodeError as exc:
            raise SandboxError(
                f"File is not valid UTF-8 and cannot be edited: {logical}"
            ) from exc

    def write(self, logical: str, content: str) -> None:
        """通过沙盒写入文件内容。"""
        r: ResolvedPath = self.resolve_write(logical)
        r.real.parent.mkdir(parents=True, exist_ok=True)
        r.real.write_text(content, encoding="utf-8")

    def append(self, logical: str, content: str) -> None:
        """通过沙盒追加文件内容。文件不存在时报错。"""
        r: ResolvedPath = self.resolve_write(logical)
        if not r.real.exists():
            raise SandboxError(f"File not found: {logical}")
        if not r.real.is_file():
            raise SandboxError(f"Not a file: {logical}")
        with r.real.open("a", encoding="utf-8") as f:
            f.write(content)

    def exists(self, logical: str) -> bool:
        """检查逻辑路径是否存在（只读检查）。"""
        try:
            r: ResolvedPath = self.resolve_read(logical)
            return r.real.exists()
        except SandboxError:
            return False

    def list_dir(self, logical: str) -> list[str]:
        """列出目录条目（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        if not r.real.is_dir():
            raise SandboxError(f"Not a directory: {logical}")
        return sorted(
            p.name for p in r.real.iterdir()
        )

    def copy(self, logical_src: str, logical_dst: str) -> None:
        """复制文件（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.is_file():
            raise SandboxError(f"Source is not a file: {logical_src}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(src.real, dst.real)

    def copy_folder(self, logical_src: str, logical_dst: str) -> None:
        """递归复制目录（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.is_dir():
            raise SandboxError(f"Source is not a directory: {logical_src}")
        if dst.real.exists():
            raise SandboxError(f"Destination already exists: {logical_dst}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(src.real, dst.real)

    def move(self, logical_src: str, logical_dst: str) -> None:
        """移动或重命名文件/目录（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.exists():
            raise SandboxError(f"Source does not exist: {logical_src}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(src.real), str(dst.real))

    def delete(self, logical: str) -> None:
        """删除文件或空目录（写入检查）。"""
        r: ResolvedPath = self.resolve_write(logical)
        if r.real.is_dir():
            r.real.rmdir()
        else:
            r.real.unlink(missing_ok=True)

    def resolve_abs(self, logical: str) -> str:
        """将逻辑路径解析为绝对路径字符串（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return str(r.real)

    def create_folder(self, logical: str, parents: bool = True) -> None:
        """创建目录（写入检查）。"""
        r: ResolvedPath = self.resolve_write(logical)
        r.real.mkdir(parents=parents, exist_ok=True)

    def delete_folder(self, logical: str) -> None:
        """递归删除目录及其所有内容（写入检查）。"""
        import shutil
        r: ResolvedPath = self.resolve_write(logical)
        if not r.real.exists():
            raise SandboxError(f"Path does not exist: {logical}")
        if not r.real.is_dir():
            raise SandboxError(f"Not a directory: {logical}")
        shutil.rmtree(str(r.real))

    def is_file(self, logical: str) -> bool:
        """检查逻辑路径是否为一个文件（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return r.real.is_file()

    def is_dir(self, logical: str) -> bool:
        """检查逻辑路径是否为一个目录（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return r.real.is_dir()

    def count_lines(self, logical: str) -> int:
        """计算文件的总行数（只读检查）。如果文件不存在或不是文件则报错。"""
        r: ResolvedPath = self.resolve_read(logical)
        if not r.real.exists():
            raise SandboxError(f"File not found: {logical}")
        if not r.real.is_file():
            raise SandboxError(f"Not a file: {logical}")
        try:
            raw = r.real.read_bytes()
            content, encoding, fallback_used = decode_text(raw)
            if fallback_used:
                logger.warning(
                    "Sandbox.count_lines decoded non-UTF-8 text | path=%s | encoding=%s",
                    logical,
                    encoding,
                )
        except FileNotFoundError:
            raise SandboxError(f"File not found: {logical}")
        if content:
            return content.count("\n") + (1 if not content.endswith("\n") else 0)
        return 0