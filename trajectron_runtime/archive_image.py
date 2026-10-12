#!/usr/bin/env python3
"""Save this image and its identity/hash for offline recovery, logging all commands."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

from runtime_paths import external_path, state_root


def logged(runtime, log_dir, label, command):
    result = subprocess.run([sys.executable, "-B", str(runtime / "run_logged.py"),
                             "--log-dir", str(log_dir),
                             "--label", label, "--quiet", "--"] + command,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command)
    path = next(line.split("=", 1)[1] for line in result.stdout.splitlines()
                if line.startswith("COMMAND_LOG="))
    return Path(path)


def main():
    runtime = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="g1-trajectron-int-ee:cpu-py36-20261012")
    parser.add_argument("--state-root", help="external logs/artifacts root")
    parser.add_argument("--artifact-dir", help="override the external archive directory")
    args = parser.parse_args()
    try:
        state = state_root(args.state_root)
        artifact_dir = external_path(args.artifact_dir or state / "artifacts")
    except ValueError as error:
        parser.error(str(error))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archive = artifact_dir / ("g1-trajectron-int-ee-cpu-py36-" + stamp + ".tar")
    if archive.exists():
        raise FileExistsError(str(archive))
    inspect_log = logged(runtime, state / "logs", "recovery-image-identity",
                         ["docker", "image", "inspect", args.image, "--format", "{{json .}}"])
    body = inspect_log.read_text().split("\n\n", 1)[1]
    inspected, _ = json.JSONDecoder().raw_decode(body)
    save_log = logged(runtime, state / "logs", "recovery-image-save",
                      ["docker", "image", "save", "--output", str(archive), args.image])
    hasher = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    with tarfile.open(str(archive), "r") as saved:
        manifest = json.load(saved.extractfile("manifest.json"))
        assert any(args.image in item.get("RepoTags", []) for item in manifest)
    digest = hasher.hexdigest()
    with archive.with_suffix(".tar.sha256").open("x") as handle:
        handle.write(digest + "  " + archive.name + "\n")
    report = {"image": args.image, "image_id": inspected["Id"],
              "repo_digests": inspected["RepoDigests"], "archive": str(archive),
              "archive_bytes": archive.stat().st_size, "archive_sha256": digest,
              "manifest_repo_tag_verified": True,
              "inspection_log": str(inspect_log), "save_log": str(save_log),
              "restore_argv": ["docker", "image", "load", "--input", str(archive)]}
    with (artifact_dir / (stamp + "_archive-manifest.json")).open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
