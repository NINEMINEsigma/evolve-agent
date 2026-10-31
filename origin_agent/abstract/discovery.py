"""Strict source-package traversal reusing framework instance collection."""

from collections.abc import Callable
import keyword
import os
from pathlib import Path
import stat
from types import ModuleType

from framework.core.discovery import Discovery


class StrictDiscovery(Discovery):
    """Import every source candidate or propagate its failure to the caller."""

    def discover(
        self,
        root: ModuleType,
        module_fn: Callable[[ModuleType], None],
    ) -> None:
        source = root.__file__
        if source is None:
            raise TypeError("Strict discovery requires a filesystem source package")
        path = Path(source)
        if path.name != "__init__.py":
            raise ValueError(f"Strict discovery requires a source package: {path}")
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f"Package source must be a regular file: {path}")
        # 动态发现必须枚举模块变量；复用父类类型收集及身份去重，不反射业务字段。
        module_fn(root)
        self._discover_directory(path.parent, root.__name__, module_fn)

    def _discover_directory(
        self,
        directory: Path,
        package_name: str,
        module_fn: Callable[[ModuleType], None],
    ) -> None:
        candidates: list[tuple[str, Path, bool]] = []
        sources: dict[str, Path] = {}
        # 当前层候选完整预检后才导入，避免同名文件/包被模块缓存静默合并。
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            metadata = path.stat()
            is_package = stat.S_ISDIR(metadata.st_mode)
            if is_package:
                if path.name == "__pycache__" or path.name.startswith("."):
                    continue
                link_metadata = path.lstat()
                if path.is_symlink() or (
                    os.name == "nt"
                    and link_metadata.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise ValueError(f"Discovery cannot traverse a linked directory: {path}")
                name = path.name
                source = path / "__init__.py"
                if not stat.S_ISREG(source.stat().st_mode):
                    raise ValueError(f"Package source must be a regular file: {source}")
            elif path.suffix == ".py" and path.name != "__init__.py":
                name = path.stem
                source = path
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(f"Module source must be a regular file: {source}")
            else:
                continue
            if not name.isidentifier() or keyword.iskeyword(name):
                raise ValueError(f"Invalid Python module name: {source}")
            module_name = f"{package_name}.{name}"
            if module_name in sources:
                raise ValueError(
                    f"Ambiguous discovery module {module_name}: "
                    f"{sources[module_name]} and {source}"
                )
            sources[module_name] = source
            candidates.append((module_name, source, is_package))

        for module_name, source, is_package in candidates:
            module = self.import_module(module_name)
            module_fn(module)
            if is_package:
                self._discover_directory(source.parent, module_name, module_fn)
