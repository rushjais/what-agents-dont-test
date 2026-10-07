"""snapshot SRC DEST: copy a project tree, skipping files its .packignore files exclude."""

import argparse
import os
import shutil
import sys

from ._build_info import VERSION
from .ignore import ignored_files


def snapshot(src, dest):
    skip = set(ignored_files(src))
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src):
        if os.path.samefile(dirpath, src) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), src).replace(os.sep, "/")
            if rel in skip:
                continue
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(dirpath, name), target)
            copied += 1
    return copied


def main(argv=None):
    ap = argparse.ArgumentParser(prog="snapshot", description=__doc__)
    ap.add_argument("--version", action="version", version=f"snapshot {VERSION}")
    ap.add_argument("src")
    ap.add_argument("dest")
    args = ap.parse_args(argv)
    if os.path.exists(args.dest) and os.listdir(args.dest):
        sys.exit(f"snapshot: {args.dest} exists and is not empty")
    n = snapshot(args.src, args.dest)
    print(f"copied {n} files to {args.dest}")
