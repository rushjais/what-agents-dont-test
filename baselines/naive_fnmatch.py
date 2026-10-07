"""Naive baseline: what a quick first attempt looks like. Should score low.

Pools every pattern from every .gitignore, ignores where each file lives,
and uses fnmatch on the basename or full path. Last matching pattern wins.
"""

import fnmatch
import os


def ignored_files(root):
    patterns, files = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            files.append(rel)
            if name == ".gitignore":
                with open(os.path.join(dirpath, name)) as f:
                    for line in f.read().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)

    out = []
    for rel in files:
        ignored = False
        for pat in patterns:
            neg = pat.startswith("!")
            p = pat[1:] if neg else pat
            p = p.strip("/")
            if fnmatch.fnmatch(os.path.basename(rel), p) or fnmatch.fnmatch(rel, p):
                ignored = not neg
        if ignored:
            out.append(rel)
    return out
