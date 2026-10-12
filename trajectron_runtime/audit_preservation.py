#!/usr/bin/env python3
"""Compare previously recorded files separately from concurrent new files."""

import argparse
import json
from pathlib import Path
import sys

from runtime_paths import external_path, state_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", help="external snapshot/report root")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        logs = state_root(args.state_root) / "logs"
        args.before = str(Path(args.before or logs / "host-before.json").resolve())
        args.after = str(Path(args.after or logs / "host-after.json").resolve())
        args.output = str(external_path(args.output or logs / "host-preservation-report.json"))
    except ValueError as error:
        parser.error(str(error))
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    original = before["protected_file_sha256"]
    current = after["protected_file_sha256"]
    removed = sorted(set(original) - set(current))
    modified = sorted(path for path in original if path in current and original[path] != current[path])
    extra = sorted(set(current) - set(original))
    python_fields = ["python_executable", "python_version", "python_prefix", "python_distributions"]
    changed_python = [field for field in python_fields if before[field] != after[field]]
    passed = not (removed or modified or changed_python)
    report = {"status": "passed" if passed else "failed",
              "scope": "previously recorded files and active host Python identity/distribution versions",
              "before_snapshot": args.before, "after_snapshot": args.after,
              "original_file_count": len(original), "removed_original_files": removed,
              "modified_original_files": modified, "changed_host_python_fields": changed_python,
              "host_distribution_count": len(before["python_distributions"]),
              "new_files_outside_this_runtime": extra,
              "new_file_note": "Additional files are listed separately; their presence does not imply modification of previously recorded files."}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
