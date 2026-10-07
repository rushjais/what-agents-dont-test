"""Cheating baseline: just ask git. Must score 100%.

It can't be wrong about git's behavior, so if it fails a case, the bug is in
the scorer's plumbing (materializing files, path normalization, comparison),
not in matching logic.
"""

import os
import shutil
import subprocess
import tempfile

GIT = ["git", "-c", "core.ignorecase=false", "-c", "core.excludesFile=" + os.devnull]


def ignored_files(root):
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "r")
        shutil.copytree(root, repo)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "XDG_CONFIG_HOME": tmp,
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        subprocess.run(GIT + ["init", "-q", "--template="], cwd=repo, env=env, check=True)
        out = subprocess.run(GIT + ["ls-files", "-z", "-o", "-i", "--exclude-standard"],
                             cwd=repo, env=env, check=True, capture_output=True).stdout
        return [p for p in out.decode().split("\0") if p]
