"""Host-only path defaults; generated state stays outside the source checkout."""

import os
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = RUNTIME_ROOT.parent


def external_path(path, source=SOURCE_ROOT):
    resolved = Path(path).expanduser().resolve()
    source = Path(source).resolve()
    if resolved == source or source in resolved.parents:
        raise ValueError("generated files must be outside the source repository: " + str(resolved))
    return resolved


def state_root(value=None):
    # A checkout can be moved without an absolute machine-specific default.
    value = value or os.environ.get("TRAJECTRON_RUNTIME_STATE")
    return external_path(value or SOURCE_ROOT.parent / "trajectron_runtime")
