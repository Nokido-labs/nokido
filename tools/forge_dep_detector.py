"""forge_dep_detector - scan Python imports, detect missing packages.
__FORGE_COLOR__ = GREEN
"""

import ast
import importlib.util
import os


def scan_imports(py_file):
    with open(py_file, encoding="utf-8", errors="replace") as f:
        tree = ast.parse(f.read())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def check_installed(pkgs):
    installed_status = {}
    for pkg in pkgs:
        try:
            spec = importlib.util.find_spec(pkg)
            installed_status[pkg] = spec is not None
        except Exception:
            installed_status[pkg] = False
    return installed_status


def suggest_install(missing):
    stdlib = {
        "os",
        "sys",
        "math",
        "datetime",
        "json",
        "re",
        "collections",
        "pathlib",
        "typing",
        "subprocess",
        "logging",
        "time",
        "io",
    }
    return [f"pip install {pkg}" for pkg in missing if pkg not in stdlib]


def scan_dir(path="app"):
    results = {}
    for root, _, files in os.walk(path):
        for file in files:
            if not file.endswith(".py"):
                continue
            py_file = os.path.join(root, file)
            try:
                imported_pkgs = scan_imports(py_file)
            except (SyntaxError, OSError):
                continue
            installed_status = check_installed(imported_pkgs)
            missing_pkgs = {pkg for pkg, installed in installed_status.items() if not installed}
            results[py_file] = {
                "missing": sorted(missing_pkgs),
                "ok": sorted(set(installed_status) - missing_pkgs),
            }
    return results


if __name__ == "__main__":
    scan_results = scan_dir("app")
    print("--- Dependency Scan Results ---")
    all_missing: set[str] = set()
    for file, deps in scan_results.items():
        if deps["missing"]:
            print(f"{file}: missing {deps['missing']}")
            all_missing.update(deps["missing"])
    if all_missing:
        print("\n--- Install suggestions ---")
        for cmd in suggest_install(all_missing):
            print(f"  {cmd}")
    else:
        print("All imports OK.")
