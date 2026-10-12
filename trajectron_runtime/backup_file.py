#!/usr/bin/env python3
"""Back up a runtime file before revising it; never edits the original."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil

from runtime_paths import state_root


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("path")
parser.add_argument("--state-root", help="external backups root")
args = parser.parse_args()
runtime = Path(__file__).resolve().parent
source = Path(args.path).resolve()
if runtime not in source.parents or not source.is_file():
    parser.error("only existing files inside the runtime directory are supported")
try:
    state = state_root(args.state_root)
except ValueError as error:
    parser.error(str(error))
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
target = state / "backups" / stamp / source.relative_to(runtime)
target.parent.mkdir(parents=True, exist_ok=False)
shutil.copy2(str(source), str(target))
print(json.dumps({"source": str(source), "backup": str(target),
                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}))
