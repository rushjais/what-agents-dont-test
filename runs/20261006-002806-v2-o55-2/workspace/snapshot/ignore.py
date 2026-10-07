"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes the syntax, but it is incomplete; the
rules below follow what `packignore` actually did:

- Lines are split with str.splitlines() and stripped of surrounding
  whitespace. Blank lines are skipped. There are no comments (`#` is
  literal) and no escapes (`\\` is literal).
- A leading `!` negates; the rest of the line is used as-is (`! x` negates
  " x"). A trailing `/` (or several) restricts the pattern to directories.
  Leading `/`s are dropped. A pattern that still contains a `/` is relative
  to its .packignore's directory; otherwise it matches a name at any depth.
- Only `*` and `?` are wildcards; `[` is literal. Within a path segment `**`
  is just `*`. A segment that is exactly `**` matches 0 to 3 directories.
- Each directory and file is decided by the rules that match it; if none
  match, it inherits its parent directory's decision. Among matching rules,
  the one from the deepest .packignore wins, then the one with the most
  literal (non-wildcard, non-`/`) characters, then the later line.
- A directory's own .packignore is read only if the directory itself is not
  excluded.
"""

import os
import re

_MAX_DOUBLE_STAR = 3


def _compile_segment(seg):
    parts = []
    for ch in seg:
        if ch == "*":
            if not parts or parts[-1] != "[^/]*":
                parts.append("[^/]*")
        elif ch == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.DOTALL)


def _match_segments(segs, parts):
    """Match compiled segments (None for `**`) against path components."""
    memo = {}

    def go(i, j):
        if (i, j) not in memo:
            if i == len(segs):
                res = j == len(parts)
            elif segs[i] is None:
                res = any(go(i + 1, k) for k in range(j, min(j + _MAX_DOUBLE_STAR, len(parts)) + 1))
            else:
                res = j < len(parts) and segs[i].fullmatch(parts[j]) is not None and go(i + 1, j + 1)
            memo[i, j] = res
        return memo[i, j]

    return go(0, 0)


class _Rule:
    def __init__(self, depth, index, negated, dir_only, anchored, segments):
        self.depth = depth          # number of path components of the .packignore's directory
        self.negated = negated
        self.dir_only = dir_only
        self.anchored = anchored
        self.segments = [None if s == "**" else _compile_segment(s) for s in segments]
        literals = sum(len(s) - s.count("*") - s.count("?") for s in segments)
        self.priority = (depth, literals, index)

    def matches(self, parts, is_dir):
        """Whether the rule matches `parts`, a path below its .packignore's directory."""
        if self.dir_only and not is_dir:
            return False
        rel = parts[self.depth:]
        if not self.anchored:
            seg = self.segments[0]
            return seg is None or seg.fullmatch(rel[-1]) is not None
        return _match_segments(self.segments, rel)


def _parse(text, depth):
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if line:
            rules.append(_Rule(depth, len(rules), negated, dir_only, anchored, line.split("/")))
    return rules


def _excluded(rules, parts, is_dir, inherited):
    best = None
    for rule in rules:
        if (best is None or rule.priority > best.priority) and rule.matches(parts, is_dir):
            best = rule
    return inherited if best is None else not best.negated


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    ignored = []

    def walk(path, parts, rules, excluded):
        # Like os.walk(followlinks=False): symlinks to directories count as
        # directories but are not descended into, so they contribute no files.
        with os.scandir(path) as it:
            entries = list(it)
        if not parts:
            entries = [e for e in entries if not (e.name == ".git" and e.is_dir())]
        if not excluded:
            for e in entries:
                if e.name == ".packignore" and not e.is_dir():
                    with open(e.path, newline="") as f:
                        rules = rules + _parse(f.read(), len(parts))
        for e in entries:
            child = parts + [e.name]
            if e.is_dir():
                if not e.is_symlink():
                    walk(e.path, child, rules, _excluded(rules, child, True, excluded))
            elif _excluded(rules, child, False, excluded):
                ignored.append("/".join(child))

    walk(root, [], [], False)
    return sorted(ignored)
