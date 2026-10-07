"""Decide which files in a project tree are ignored by its .gitignore files.

This currently delegates to git: it copies the tree into a scratch repository
and asks `git ls-files` which untracked files are ignored.
"""

import os
import shutil
import subprocess
import tempfile

# Pin the settings that would otherwise make the answer depend on the machine:
# no global excludes file, case-sensitive matching.
_GIT = ["git", "-c", "core.ignorecase=false", "-c", "core.excludesFile=" + os.devnull]


def _env(home):
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": home,
        "XDG_CONFIG_HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def ignored_files(root):
    """Return the files under `root` that its .gitignore files ignore.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. Only .gitignore files inside
    `root` are consulted; a `.git` directory directly under `root` is skipped.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        shutil.copytree(root, repo, symlinks=True,
                        ignore=lambda d, names: [".git"] if os.path.samefile(d, root) else [])
        env = _env(tmp)
        subprocess.run(_GIT + ["init", "-q", "--template="], cwd=repo, env=env,
                       check=True, capture_output=True)
        out = subprocess.run(_GIT + ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"],
                             cwd=repo, env=env, check=True, capture_output=True).stdout
    return sorted(p for p in out.decode().split("\0") if p)
