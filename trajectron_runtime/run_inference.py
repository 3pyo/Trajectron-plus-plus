#!/usr/bin/env python3
"""Host stdlib launcher: read-only source + one JSONL; external results only."""

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="host frames.jsonl; mounted as one read-only file")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--image", default="g1-trajectron-int-ee:cpu-py36-20261012")
    parser.add_argument("--state-root")
    parser.add_argument("--output-root")
    timing = parser.add_mutually_exclusive_group()
    timing.add_argument("--end-offset-sec", type=float)
    timing.add_argument("--prediction-time-ns", type=int)
    parser.add_argument("--observation-start-ns", type=int)
    parser.add_argument("--max-gap-sec", type=float, default=0.5)
    parser.add_argument("--min-history-points", type=int, default=3)
    parser.add_argument("--target-session")
    parser.add_argument("--target-person-id", type=int)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--debug-future", action="store_true")
    args = parser.parse_args()
    source = runtime.parent.resolve()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        parser.error("input must be an existing JSONL file")
    try:
        state = state_root(args.state_root)
        root = external_path(args.output_root or state / "results" / "g1-inference")
    except ValueError as error:
        parser.error(str(error))
    if any("," in str(path) for path in (source, input_path, root)):
        parser.error("Docker bind-mount paths must not contain commas")
    output = root / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    inference = ["python", "/opt/trajectron-src/experiments/g1/infer.py",
                 "--input", "/input/frames.jsonl", "--output", "/results/prediction",
                 "--experiment-id", args.experiment_id]
    for name in ("end_offset_sec", "prediction_time_ns", "observation_start_ns", "max_gap_sec",
                 "min_history_points", "target_session", "target_person_id", "samples", "seed"):
        value = getattr(args, name)
        if value is not None:
            inference.extend(["--" + name.replace("_", "-"), str(value)])
    if args.debug_future:
        inference.append("--debug-future")
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--runtime", "runc",
               "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges=true", "--user", "{}:{}".format(os.getuid(), os.getgid()),
               "--cpus", "2", "--memory", "2g", "--memory-swap", "2g", "--pids-limit", "256",
               "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=1777",
               "--mount", "type=bind,source={},target=/opt/trajectron-src,readonly".format(source),
               "--mount", "type=bind,source={},target=/input/frames.jsonl,readonly".format(input_path),
               "--mount", "type=bind,source={},target=/results".format(output), args.image] + inference
    manifest = {"image": args.image, "source": str(source), "input": str(input_path),
                "output": str(output), "argv": command, "network": "none", "gpu": False,
                "mounts": {"source": "read-only", "single_input_jsonl": "read-only", "new_results": "writable"}}
    with (output / "launch-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print("RESULT_DIRECTORY=" + str(output), flush=True)
    status = subprocess.call([sys.executable, "-B", str(runtime / "run_logged.py"),
                              "--log-dir", str(state / "logs"), "--label", "g1-inference-container", "--"] + command)
    with (output / "exit-status.json").open("x", encoding="utf-8") as stream:
        json.dump({"exit_code": status}, stream)
        stream.write("\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
