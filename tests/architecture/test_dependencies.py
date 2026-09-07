import ast
from pathlib import Path

import flynn_agents_sdk


def test_contracts_are_standard_library_only_and_runtime_avoids_adapters():
    root = Path(flynn_agents_sdk.__file__).parent
    for name, forbidden in {
        "contracts.py": ("flynn_agents_sdk",),
        "runtime.py": ("flynn_agents_sdk.inference", "flynn_agents_sdk.sqlite_run"),
    }.items():
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            else:
                continue
            for module in imports:
                assert not module.startswith(forbidden)
                assert not module.startswith(("tests", "examples", "arc_harness"))


def test_all_sdk_modules_exclude_harness_and_blender_dependencies():
    root = Path(flynn_agents_sdk.__file__).parent
    forbidden = ("arc_harness", "arc_agi", "arcengine", "vfx_harness", "bpy", "bmesh")
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            else:
                continue
            for module in imports:
                assert module.split(".")[0] not in forbidden, (
                    f"{path.name} imports domain dependency {module}; see docs/OWNERSHIP.md"
                )
