"""Library baseline: the popular `pathspec` package, wired up the way git walks a tree.

pathspec only matches against one pattern list. Git's extra rules are added here:
  - each .gitignore's patterns are relative to its own directory
  - deeper .gitignore files take precedence (last match wins, root first)
  - an ignored directory is never entered, so nothing under it can be
    re-included and its own .gitignore is never read

This measures how hard the task is: if a widely used library plus careful
wiring still misses cases, the task isn't trivial.
"""

import os

from pathspec.patterns.gitwildmatch import GitWildMatchPattern


def _load(path):
    with open(path) as f:
        pats = [GitWildMatchPattern(line) for line in f.read().splitlines()]
    return [p for p in pats if p.include is not None]


def _decide(stack, rel, is_dir):
    result = False
    for base, pats in stack:
        sub = rel[len(base):] + ("/" if is_dir else "")
        for pat in pats:
            if pat.match_file(sub) is not None:
                result = pat.include
    return result


def ignored_files(root):
    out = []

    def walk(dirrel, stack, parent_ignored):
        abspath = os.path.join(root, dirrel)
        entries = sorted(os.listdir(abspath))
        if not parent_ignored and ".gitignore" in entries:
            stack = stack + [(dirrel, _load(os.path.join(abspath, ".gitignore")))]
        for e in entries:
            rel = dirrel + e
            if os.path.isdir(os.path.join(root, rel)):
                walk(rel + "/", stack, parent_ignored or _decide(stack, rel, True))
            elif parent_ignored or _decide(stack, rel, False):
                out.append(rel)

    walk("", [], False)
    return out
