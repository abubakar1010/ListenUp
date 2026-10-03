"""A module may use another module only through that module's service.py (Architecture 4.3)."""

import ast
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parents[2] / "src" / "listenup" / "modules"
PREFIX = "listenup.modules."


def imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def violations() -> list[str]:
    found: list[str] = []
    for path in MODULES_DIR.rglob("*.py"):
        owner = path.relative_to(MODULES_DIR).parts[0]
        for name in imported_names(ast.parse(path.read_text(), filename=str(path))):
            if not name.startswith(PREFIX):
                continue
            parts = name[len(PREFIX) :].split(".")
            target = parts[0]
            if target == owner:
                continue
            # Allowed: `from listenup.modules.x import service` or `listenup.modules.x.service...`.
            if len(parts) >= 2 and parts[1] == "service":
                continue
            if len(parts) == 1:
                continue  # the package itself; its members are checked as separate names
            found.append(f"{path.relative_to(MODULES_DIR)} imports {name}")
    return found


def test_modules_use_each_other_only_through_service() -> None:
    assert violations() == []
