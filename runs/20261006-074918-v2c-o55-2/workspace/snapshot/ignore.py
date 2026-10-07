"""Decide which files in a project tree are excluded by its .packignore files.

This currently delegates to `packignore`, the legacy exclusion engine (see
docs/PACKIGNORE.md), via the client in tools/.
"""

import os
import subprocess
import sys

_CLIENT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "packignore")


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    out = subprocess.run([sys.executable, _CLIENT, root], check=True, capture_output=True,
                         text=True).stdout
    return sorted(line for line in out.splitlines() if line)
