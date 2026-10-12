#!/usr/bin/env python3
"""Launch the dependency check with only read-only source and new result mounts."""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from runtime_paths import external_path, state_root


DEFAULT_IMAGE = "g1-trajectron-int-ee:cpu-py36-20261012"


def main():
    runtime = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--source", default=str(runtime.parent))
    parser.add_argument("--state-root", help="external logs/results root")
    parser.add_argument("--output-root", help="override the external results directory")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not (source / "experiments/nuScenes/models/int_ee/model_registrar-12.pt").is_file():
        parser.error("source must contain the int_ee checkpoint 12")
    try:
        state = external_path(state_root(args.state_root), source)
        output_root = external_path(external_path(args.output_root or state / "results"), source)
    except ValueError as error:
        parser.error(str(error))
    if "," in str(source) or "," in str(output_root):
        parser.error("Docker bind-mount paths must not contain commas")
    run_name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = output_root / run_name
    output.mkdir(parents=True, exist_ok=False)
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--runtime", "runc",
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges=true", "--user", "{}:{}".format(os.getuid(), os.getgid()),
               "--cpus", "2", "--memory", "2g", "--memory-swap", "2g", "--pids-limit", "256",
               "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777",
               "--mount", "type=bind,source={},target=/opt/trajectron-src,readonly".format(source),
               "--mount", "type=bind,source={},target=/results".format(output),
               args.image, "python", "/opt/runtime/verify_runtime.py"]
    manifest = {"image": args.image, "source": str(source), "output": str(output), "argv": command,
                "state_root": str(state), "log_directory": str(state / "logs"),
                "mounts": {"/opt/trajectron-src": "read-only", "/results": "new output directory"},
                "network": "none", "gpu": False, "root_filesystem": "read-only"}
    with (output / "launch-manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print("RESULT_DIRECTORY=" + str(output), flush=True)
    status = subprocess.call([sys.executable, "-B", str(runtime / "run_logged.py"),
                              "--log-dir", str(state / "logs"),
                              "--label", "container-verification", "--"] + command)
    with (output / "exit-status.json").open("x", encoding="utf-8") as handle:
        json.dump({"exit_code": status}, handle)
        handle.write("\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
