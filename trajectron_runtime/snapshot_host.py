#!/usr/bin/env python3
"""Read-only fingerprint of the existing source and active host Python environment."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

from runtime_paths import external_path, state_root


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--compare")
    parser.add_argument("--workspace-root", required=True,
                        help="explicit source workspace to audit, e.g. /home/choi/g1_ros2_ws/src")
    parser.add_argument("--state-root", help="external state directory to exclude from the audit")
    args = parser.parse_args()
    runtime = Path(__file__).resolve().parent
    workspace = Path(args.workspace_root).expanduser().resolve()
    if not workspace.is_dir():
        parser.error("workspace root must be an existing directory")
    try:
        state = state_root(args.state_root)
        output = external_path(args.output)
    except ValueError as error:
        parser.error(str(error))
    files = {}
    extensions = {".py", ".cpp", ".hpp", ".h", ".c", ".yaml", ".yml", ".xml",
                  ".toml", ".cfg", ".ini", ".sh", ".bash", ".md", ".repos", ".pt"}
    for path in sorted(workspace.rglob("*")):
        if runtime in path.parents or state in path.parents or any(part in {".git", "__pycache__", "node_modules"}
                                          for part in path.relative_to(workspace).parts):
            continue
        if path.is_file() and (path.suffix in extensions or path.name in
                               {"requirements.txt", "CMakeLists.txt", "Dockerfile"}):
            files[str(path)] = digest(path)
    for path in [Path.home() / ".bashrc", Path.home() / ".profile", Path.home() / ".bash_profile",
                 workspace.parent / ".python-version", workspace.parent / "install/setup.bash"]:
        if path.is_file():
            files[str(path)] = digest(path)
    distributions = sorted((d.metadata.get("Name", ""), d.version)
                           for d in importlib.metadata.distributions())
    snapshot = {"python_executable": sys.executable, "python_version": sys.version,
                "python_prefix": sys.prefix, "python_distributions": distributions,
                "protected_file_sha256": files}
    if args.compare:
        before = json.loads(Path(args.compare).read_text())
        # JSON turns tuples into lists; normalize before comparing.
        current = json.loads(json.dumps(snapshot))
        changes = {key: {"before": before[key], "after": current[key]}
                   for key in before if before[key] != current[key]}
        snapshot["comparison"] = {"unchanged": not changes, "changed_sections": list(changes)}
        if changes:
            snapshot["comparison"]["changes"] = changes
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"output": args.output, "protected_file_count": len(files),
                      "host_distribution_count": len(distributions),
                      "unchanged": snapshot.get("comparison", {}).get("unchanged")}, indent=2))
    if args.compare and not snapshot["comparison"]["unchanged"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
