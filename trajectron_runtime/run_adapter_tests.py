#!/usr/bin/env python3
"""Run temporal-isolation regressions with two read-only G1 fixture files."""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from runtime_paths import external_path, state_root


def main():
    runtime = Path(__file__).resolve().parent
    source = runtime.parent.resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-root", required=True, help="directory containing safe_2 and danger_2")
    parser.add_argument("--state-root")
    parser.add_argument("--output-root")
    parser.add_argument("--image", default="g1-trajectron-int-ee:cpu-py36-20261012")
    args = parser.parse_args()
    fixtures = Path(args.fixtures_root).expanduser().resolve()
    paths = {case: fixtures / case / "metadata/frames.jsonl" for case in ("safe_2", "danger_2")}
    if not all(path.is_file() for path in paths.values()):
        parser.error("both safe_2 and danger_2 metadata/frames.jsonl fixtures are required")
    try:
        state = state_root(args.state_root)
        root = external_path(args.output_root or state / "results" / "g1-tests")
    except ValueError as error:
        parser.error(str(error))
    if any("," in str(path) for path in [source, root] + list(paths.values())):
        parser.error("Docker bind-mount paths must not contain commas")
    output = root / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--runtime", "runc",
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges=true", "--user", "{}:{}".format(os.getuid(), os.getgid()),
               "--cpus", "2", "--memory", "2g", "--memory-swap", "2g", "--pids-limit", "256",
               "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777",
               "--mount", "type=bind,source={},target=/opt/trajectron-src,readonly".format(source),
               "--mount", "type=bind,source={},target=/results".format(output)]
    for case, path in paths.items():
        command.extend(["--mount", "type=bind,source={},target=/fixtures/{}/metadata/frames.jsonl,readonly".format(path, case)])
    command.extend([args.image, "python", "/opt/trajectron-src/experiments/g1/test_adapter.py"])
    with (output / "launch-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"argv": command, "image": args.image, "output": str(output)}, stream, indent=2)
        stream.write("\n")
    print("TEST_RESULT_DIRECTORY=" + str(output), flush=True)
    status = subprocess.call([sys.executable, "-B", str(runtime / "run_logged.py"),
                              "--log-dir", str(state / "logs"), "--label", "g1-adapter-tests", "--"] + command)
    with (output / "exit-status.json").open("x", encoding="utf-8") as stream:
        json.dump({"exit_code": status}, stream)
        stream.write("\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
