#!/usr/bin/env python3
"""Utility for installing the latest Xcode Command Line Tools on macOS.

This script detects the newest available "Command Line Tools for Xcode" update
via the ``softwareupdate`` utility. It then prompts the user for confirmation
before attempting to install the update. The script is intentionally cautious
and will not perform any installation unless explicitly approved by the user.

The script is designed for macOS Big Sur and later, but relies only on
``softwareupdate`` so it should work on most macOS versions that provide this
utility.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import List, Optional, Tuple


LABEL_PATTERN = re.compile(r"\*\s*(Command Line Tools for Xcode-[^\s]+)")
VERSION_PATTERN = re.compile(r"Command Line Tools for Xcode-([0-9.]+)")


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run ``cmd`` returning a CompletedProcess with text output."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _parse_labels(output: str) -> List[Tuple[str, Tuple[int, ...]]]:
    """Return available labels and versions from ``softwareupdate --list``."""
    results: List[Tuple[str, Tuple[int, ...]]] = []
    for line in output.splitlines():
        label_match = LABEL_PATTERN.search(line)
        if not label_match:
            continue
        label = label_match.group(1).strip()
        version_match = VERSION_PATTERN.search(label)
        if not version_match:
            continue
        version_tuple = tuple(int(x) for x in version_match.group(1).split('.'))
        results.append((label, version_tuple))
    return results


def get_latest_label() -> Optional[Tuple[str, Tuple[int, ...]]]:
    """Return the latest available Command Line Tools label and version."""
    proc = _run(["softwareupdate", "--list"])
    if proc.returncode != 0:
        print("softwareupdate --list failed:", proc.stderr.strip(), file=sys.stderr)
        return None

    labels = _parse_labels(proc.stdout)
    if not labels:
        print("No Command Line Tools updates were found.")
        return None
    labels.sort(key=lambda item: item[1], reverse=True)
    return labels[0]


def install_label(label: str) -> int:
    """Attempt to install ``label`` using ``softwareupdate``.

    Returns the ``softwareupdate`` return code.
    """
    print(f"Attempting to install '{label}'. You may be prompted for your password.")
    cmd = ["sudo", "softwareupdate", "--install", label]
    proc = subprocess.run(cmd)
    if proc.returncode == 0:
        print("Installation completed successfully.")
    else:
        print(f"Installation failed with return code {proc.returncode}.")
    return proc.returncode


def main() -> int:
    if sys.platform != "darwin":
        print("This utility is intended to run on macOS.")
        return 1

    latest = get_latest_label()
    if not latest:
        return 1

    label, version = latest
    version_str = '.'.join(map(str, version))
    print(f"Latest Command Line Tools available: {version_str} ({label})")
    answer = input("Install now? [y/N]: ").strip().lower()
    if answer != "y":
        print("Installation cancelled.")
        return 0
    return install_label(label)


if __name__ == "__main__":
    raise SystemExit(main())
