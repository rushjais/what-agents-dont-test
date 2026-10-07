"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. Its behaviour differs from docs/PACKIGNORE.md in several places; the
rules below are what `packignore` actually does.

Parsing (per .packignore file):

- The text is split with str.splitlines() (so "\\r", "\\v", "\\f", "\\x1c",
  "\\x85", "\\u2028", ... all end a line) and each line is str.strip()ped.
- Empty lines and lines starting with ";" are skipped. "#" is NOT a comment.
- A leading "!" negates the pattern. Nothing else is stripped after it.
- There are no escapes or character classes: "\\", "[" and "]" are literal.
- Trailing "/"s make the pattern match directories only; leading "/"s are
  dropped. If the remaining pattern contains a "/" it is anchored to the
  directory holding the .packignore, otherwise it matches a name at any depth
  below it. Patterns that end up empty are skipped.
- Within a segment "*" matches any run of characters and "?" exactly one. A
  segment that is exactly "**" matches zero or more whole segments (so "a/**"
  also matches "a" itself). An empty segment ("a//b") never matches.

Matching:

- A file is checked together with each of its ancestor directories. Every
  pattern matching any of those paths is a candidate, and the winner is the
  one with, in order of priority: the deepest matched path, the most deeply
  nested .packignore, the most literal (non "*", "?", "/") characters, the
  latest line. The file is excluded if the winner is not negated. So "!x" can
  re-include a file inside an excluded directory.
- A .packignore in a subdirectory is only read if that directory itself is
  not excluded (as decided by the rules above, using the outer files).
"""

import os

_NAME = ".packignore"


def _parse(text):
    """Return the rules in a .packignore file's text, in file order.

    Each rule is (segments, dir_only, negated, literal_count).
    """
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        literals = sum(1 for c in line if c not in "*?/")
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if not line:
            continue
        segments = line.split("/")
        if not anchored:
            segments = ["**"] + segments
        rules.append((tuple(segments), dir_only, negated, literals))
    return rules


def _match_name(pat, name):
    """Match one path component against one pattern segment ("*" and "?" only)."""
    # Classic two-pointer wildcard match with backtracking to the last "*".
    p = n = 0
    star = mark = -1
    while n < len(name):
        if p < len(pat) and (pat[p] == "?" or (pat[p] != "*" and pat[p] == name[n])):
            p += 1
            n += 1
        elif p < len(pat) and pat[p] == "*":
            star, mark = p, n
            p += 1
        elif star >= 0:
            p = star + 1
            mark += 1
            n = mark
        else:
            return False
    while p < len(pat) and pat[p] == "*":
        p += 1
    return p == len(pat)


def _match(segments, parts):
    """Match pattern segments against path components; "**" spans zero or more."""
    memo = {}

    def rec(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(segments):
            result = j == len(parts)
        elif segments[i] == "**":
            result = any(rec(i + 1, k) for k in range(j, len(parts) + 1))
        else:
            result = (j < len(parts) and segments[i] != ""
                      and _match_name(segments[i], parts[j]) and rec(i + 1, j + 1))
        memo[key] = result
        return result

    return rec(0, 0)


def _excluded(parts, is_dir, rulesets):
    """Decide whether the path `parts` is excluded.

    `rulesets` holds (base_depth, rules) for every loaded .packignore in an
    ancestor directory of `parts`, base_depth being that directory's depth.
    """
    for depth in range(len(parts), 0, -1):
        best = None
        prefix_is_dir = is_dir or depth < len(parts)
        for base_depth, rules in rulesets:
            if base_depth >= depth:
                continue
            rel = parts[base_depth:depth]
            for index, (segments, dir_only, negated, literals) in enumerate(rules):
                if dir_only and not prefix_is_dir:
                    continue
                key = (base_depth, literals, index)
                if (best is None or key > best[0]) and _match(segments, rel):
                    best = (key, negated)
        if best is not None:
            return not best[1]
    return False


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    ignored = []
    # Loaded rulesets for each directory, keyed by its path components.
    active = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        parts = () if rel == os.curdir else tuple(rel.split(os.sep))
        if not parts and ".git" in dirnames:
            dirnames.remove(".git")
        inherited = active[parts[:-1]] if parts else []
        rulesets = inherited
        if _NAME in filenames and not (parts and _excluded(parts, True, inherited)):
            rulesets = inherited + [(len(parts), _parse(_read(os.path.join(dirpath, _NAME))))]
        active[parts] = rulesets
        for name in filenames:
            if _excluded(parts + (name,), False, rulesets):
                ignored.append("/".join(parts + (name,)))
    return sorted(ignored)
