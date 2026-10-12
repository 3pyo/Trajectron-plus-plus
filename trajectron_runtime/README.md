# Trajectron++ CPU dependency container

This directory provides the Docker environment for the author's `int_ee`
checkpoint 12. Its scope is dependencies, imports and checkpoint/model
initialization. G1 data adaptation, experiment inference and training are outside
this implementation.

## Source and generated files

The fork tracks this implementation alongside its model code. Generated state
is kept outside the checkout, so it is neither committed nor exposed through
the read-only source mount:

```text
baselines/
├── Trajectron-plus-plus/
│   ├── trajectron/
│   ├── experiments/
│   └── trajectron_runtime/       # tracked implementation
└── trajectron_runtime/           # external generated state, original location
    ├── logs/                    # command journal, host audit, buildx state
    ├── results/                 # timestamped verification results
    ├── backups/                 # original implementation and revisions
    └── artifacts/               # Docker image archive and checksum
```

Defaults are resolved from the scripts' locations, independently of the current
working directory. The source defaults to the parent checkout. State defaults
to its sibling `trajectron_runtime/`. Set `TRAJECTRON_RUNTIME_STATE` or pass
`--state-root` to use another external directory. A CLI state root overrides the
environment variable. `--log-dir`, `--output-root` and `--artifact-dir` override
the corresponding destinations. A selected state root is forwarded to nested
command loggers. Generated paths inside the source checkout are rejected.

## Isolation and versions

All dependency installation and native compilation happen inside Docker.
Host Python/ROS packages, shell configuration and drivers are unchanged. Host
helpers use only the existing Python standard library with bytecode disabled.
The snapshot helper needs host Python 3.8+; the container uses Python 3.6.15.

The source and checkpoint are mounted read-only; only a fresh external result
directory is writable on the host. The container has no network, GPU, host
Python/ROS, home or Docker socket mount. It uses a read-only root filesystem,
256 MiB `/tmp` tmpfs, no capabilities, no-new-privileges, numeric host UID/GID,
`runc`, 2 CPUs, 2 GiB RAM and 256 PIDs. It is removed on exit.

Python **3.6.15** and PyTorch **1.4.0+cpu** retain the author's inference stack.
[requirements.lock](requirements.lock) pins the full inference dependency
closure. Both Docker base images are fixed by linux/amd64 digest. The builder
compiles ncls; runtime installs wheels offline through an ephemeral BuildKit
mount. GLib/GThread/PCRE libraries for OpenCV are copied from the pinned builder,
with provenance and hashes recorded. No host or container apt installation is
needed. Training/TensorBoard, notebooks and raw nuScenes preprocessing optional
dependencies are outside the verified scope.

## Build and verification

Run from the Trajectron++ repository root:

```bash
python3 -B trajectron_runtime/run_logged.py --label image-build -- \
  env BUILDX_CONFIG="$(pwd)/../trajectron_runtime/logs/buildx-state" \
  docker build --platform linux/amd64 --progress plain \
  --tag g1-trajectron-int-ee:cpu-py36-20261012 trajectron_runtime

python3 -B trajectron_runtime/run_logged.py --label verify-launch -- \
  python3 -B trajectron_runtime/verify_container.py
```

Keep the Docker build context at `trajectron_runtime/`, rather than the checkout
root: Dockerfile COPY paths and its allowlist `.dockerignore` expect this context.
With a custom state root, set `BUILDX_CONFIG` explicitly to that state's
`logs/buildx-state` as well. Moving the host helpers does not require rebuilding
the existing image; Dockerfile, requirements and container validator are unchanged.

Verification creates an external timestamped results directory and records
exact Docker arguments and status. The 32 checks cover package versions,
imports, native extensions, CPU operations, Environment serialization,
checkpoint 12 loading, both node model constructors, finite parameters,
original evaluation/online `--help` entrypoints and read-only source access.
There is no experiment input or trajectory prediction.

Results include `dependency-report.json`, installed versions, wheel/native
library hashes, `launch-manifest.json` and `exit-status.json`.

## Logging, backup and host audit

External `logs/commands.jsonl` records argv, timestamps, working directory,
status and stdout/stderr log paths. Build logs retain Dockerfile RUN output.
Earlier logs and result paths are preserved without rewriting their history.

Before modifying an existing runtime file:

```bash
python3 -B trajectron_runtime/run_logged.py --label backup-file -- \
  python3 -B trajectron_runtime/backup_file.py trajectron_runtime/verify_container.py
```

Host snapshots require an explicit workspace root, so moving the checkout does
not silently change the audited area:

```bash
python3 -B trajectron_runtime/run_logged.py --label host-snapshot -- \
  python3 -B trajectron_runtime/snapshot_host.py \
  --workspace-root /home/choi/g1_ros2_ws/src \
  --output ../trajectron_runtime/logs/host-new.json
```

Snapshots exclude this implementation and the selected external state directory.
They record existing source/config/checkpoints, selected shell/ROS setup files,
and active host Python identity/distribution versions. This is not a whole-host
filesystem snapshot. `audit_preservation.py` compares recorded original files
separately from concurrent additions; use `--before`, `--after`, `--output`
for a fresh report without overwriting an existing record.

## Recovery

The existing image archive remains in external `artifacts/`, together with its
checksum and manifest. See [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)
for its identity and [RELOCATION_REPORT.md](RELOCATION_REPORT.md) for relocation
verification and backup paths. To restore that image from the repository root:

```bash
python3 -B trajectron_runtime/run_logged.py --label image-restore -- \
  docker image load --input \
  ../trajectron_runtime/artifacts/g1-trajectron-int-ee-cpu-py36-20261012T080237.178963Z.tar
```

Verify the matching `.tar.sha256` in the artifacts directory first. The archive
contains dependencies and the validator; the source/checkpoint remains a
separate mount. `archive_image.py` supports `--state-root` and `--artifact-dir`
for future exports. No image load, image deletion or Docker prune is performed
as part of relocation.
