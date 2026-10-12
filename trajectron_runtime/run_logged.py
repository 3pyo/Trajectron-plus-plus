#!/usr/bin/env python3
"""Record a command, its output and exit status without installing host packages."""

import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from runtime_paths import external_path, state_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--state-root", help="external state directory; defaults to a sibling of the checkout")
    parser.add_argument("--log-dir", help="override the external command-log directory")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    if not all(c.isalnum() or c in "-_" for c in args.label):
        parser.error("label must contain only letters, numbers, '-' and '_'")
    try:
        log_dir = external_path(args.log_dir or state_root(args.state_root) / "logs")
    except ValueError as error:
        parser.error(str(error))
    log_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.datetime.now(datetime.timezone.utc)
    stem = started.strftime("%Y%m%dT%H%M%S.%fZ") + "_" + args.label
    output_path = log_dir / (stem + ".log")
    record = {
        "started_at": started.isoformat(),
        "label": args.label,
        "argv": command,
        "shell_command": " ".join(shlex.quote(value) for value in command),
        "cwd": os.getcwd(),
        "output_log": str(output_path),
    }
    journal = log_dir / "commands.jsonl"
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record, event="start"), ensure_ascii=False) + "\n")
    print("COMMAND_LOG=" + str(output_path), flush=True)
    beginning = time.monotonic()
    with output_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n\n")
        output.flush()
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1)
            for line in process.stdout:
                output.write(line)
                output.flush()
                if not args.quiet:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            status = process.wait()
        except OSError as error:
            output.write(str(error) + "\n")
            status = 127
        record.update(event="finish", exit_code=status,
                      elapsed_seconds=round(time.monotonic() - beginning, 3),
                      finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        output.write("\n" + json.dumps(record, ensure_ascii=False) + "\n")
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("EXIT_CODE=" + str(status), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
