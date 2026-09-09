"""Bounded retries for transient Windows locks on local atomic file operations."""

import os
from pathlib import Path
import time


def atomic_replace(source: Path, destination: Path) -> None:
    """Retry only permission-denied local replacements; never remote effects."""
    for attempt in range(5):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            time.sleep(0.05 * (2**attempt))


def publish_directory(source: Path, destination: Path) -> None:
    """Rename a complete generation without replacing an existing directory."""
    for attempt in range(5):
        if destination.exists():
            raise FileExistsError("Completed generation destination already exists.")
        try:
            source.rename(destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            time.sleep(0.05 * (2**attempt))
