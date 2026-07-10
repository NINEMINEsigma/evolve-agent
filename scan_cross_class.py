"""扫描 origin_agent/ 中可能的跨类单下划线字段外部访问。

只读扫描，不修改任何文件。
"""
from __future__ import annotations

import ast
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\__TEMP__\evolve-agent\origin_agent")


def find_classes(node: ast.AST, mod_name: str) -> dict[str, tuple[str, list[str]]]:
    """返回 {类名: (定义文件, [父类名])}。"""
    result: dict[str, tuple[str, list[str]]] = {}
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            bases = []
            for b in child.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            result[child.name] = (mod_name, bases)
            result.update(find_classes(child, mod_name))
    return result


def get_class_fields(node: ast.ClassDef) -> set[str]:
    """从 __init__ 中提取 self._xxx 字段名。"""
    fields: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef) and child.name == "__init__":
            for sub in ast.walk(child):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                    if sub.value.id == "self" and sub.attr.startswith("_"):
                        fields.add(sub.attr)
    return fields


def build_inheritance_graph(classes: dict[str, tuple[str, list[str]]]) -> dict[str, set[str]]:
    """返回每个类的所有祖先（包括间接）。"""
    ancestors: dict[str, set[str]] = {name: set() for name in classes}

    def dfs(name: str, visited: set[str]) -> set[str]:
        if name in visited:
            return set()
        visited.add(name)
        result: set[str] = set()
        _, bases = classes[name]
        for base in bases:
            if base in classes:
                result.add(base)
                result.update(dfs(base, visited))
        return result

    for name in classes:
        ancestors[name] = dfs(name, set())
    return ancestors


def scan() -> list[tuple[str, int, str, str]]:
    """扫描并返回 (文件, 行号, 访问表达式, 说明)。"""
    all_classes: dict[str, tuple[str, list[str]]] = {}
    class_fields: dict[str, set[str]] = {}

    for path in ROOT.rglob("*.py"):
        if "mcp" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        mod_classes = find_classes(tree, rel)
        all_classes.update(mod_classes)
        for name, (_, _) in mod_classes.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == name:
                    class_fields[name] = get_class_fields(node)

    ancestors = build_inheritance_graph(all_classes)

    issues: list[tuple[str, int, str, str]] = []

    for path in ROOT.rglob("*.py"):
        if "mcp" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        # 当前文件中的类名 -> 方法定义
        current_classes: dict[str, ast.ClassDef] = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                if isinstance(node.value, ast.Name) and node.value.id == "self":
                    continue

                # 尝试找到当前所在的类
                enclosing_class: str | None = None
                for cls_name, cls_node in current_classes.items():
                    if cls_node.lineno <= node.lineno <= getattr(cls_node, "end_lineno", 10**9):
                        # 检查 node 是否在 cls_node 的方法中
                        for method in cls_node.body:
                            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if method.lineno <= node.lineno <= getattr(method, "end_lineno", 10**9):
                                    enclosing_class = cls_name
                                    break

                target_field = node.attr

                # 如果访问的是 self，检查是否在当前类或父类中定义
                if isinstance(node.value, ast.Name) and node.value.id == "self" and enclosing_class:
                    all_defined = class_fields.get(enclosing_class, set())
                    for anc in ancestors.get(enclosing_class, set()):
                        all_defined |= class_fields.get(anc, set())
                    if target_field in all_defined:
                        continue

                # 否则，如果 target_field 是某个已知类的字段，且当前类不是该类的子类，则为跨类访问
                owner_classes = [
                    cls_name
                    for cls_name, fields in class_fields.items()
                    if target_field in fields
                ]
                if owner_classes and enclosing_class:
                    is_descendant = any(
                        enclosing_class == owner or owner in ancestors.get(enclosing_class, set())
                        for owner in owner_classes
                    )
                    if not is_descendant:
                        expr = ast.unparse(node)
                        issues.append((rel, node.lineno, expr, f"访问 {owner_classes[0]} 的内部字段"))

    return issues


if __name__ == "__main__":
    issues = scan()
    if issues:
        print(f"发现 {len(issues)} 处可疑跨类下划线字段访问：")
        for rel, lineno, expr, note in issues[:100]:
            print(f"  {rel}:{lineno}  {expr}  ({note})")
    else:
        print("未发现明显跨类下划线字段访问。")