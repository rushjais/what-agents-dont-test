"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes the original, but the rules below follow
what `packignore` actually did where the two disagree:

- Lines are split with str.splitlines() and stripped of surrounding
  whitespace. Blank lines and lines starting with ";" are skipped ("#" is not
  a comment). There is no escaping: "\\" is literal.
- "!" negates the rest of the line, which is not stripped again.
- Leading and trailing "/" are removed; a trailing "/" makes the pattern match
  directories only, and any remaining "/" anchors it to the .packignore's
  directory. Otherwise the pattern matches a name at any depth.
- "{a,b}" expands to the alternatives "a" and "b", textually, after the
  above: "{" pairs with the next "}" (no nesting), and an unpaired "{" or "}"
  is literal.
- "*" matches any run of characters within a segment, "?" exactly one; "[" is
  literal. A segment that is exactly "**" matches zero to three segments (not
  more: packignore capped it).
- Of the patterns matching a path, those from a deeper .packignore win;
  within one file the most specific pattern wins, i.e. the one with the most
  characters other than "*", "?", "/", "{", "}" and ","; ties go to the later
  line. A path
  no pattern matches inherits its directory's state, so a directory's
  exclusion can be overridden for paths inside it.
- A .packignore inside an excluded directory is not read. If one that would
  be read is a directory, packignore failed with an internal error; so does
  ignored_files(), by raising PackignoreError.
"""

import itertools
import os
import re
import unicodedata


class PackignoreError(Exception):
    """The tree is one packignore could not process."""


def _compile(line):
    """Turn one .packignore line into (regex, negate, dir_only, anchored, score), or None."""
    line = line.strip()
    if not line or line.startswith(";"):
        return None
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    dir_only = line.endswith("/")
    line = line.rstrip("/")
    anchored = "/" in line
    line = line.lstrip("/")
    if not line:
        return None
    score = sum(c not in "*?/{}," for c in line)
    regex = "|".join(dict.fromkeys(map(_translate, _expand_braces(line))))
    return re.compile(regex, re.S), negate, dir_only, anchored, score


def _expand_braces(pattern):
    """Expand every "{a,b,...}" group in `pattern`, returning all combinations."""
    pieces = []
    i = 0
    while i < len(pattern):
        end = pattern.find("}", i + 1) if pattern[i] == "{" else -1
        if end == -1:
            pieces.append([pattern[i]])
            i += 1
        else:
            pieces.append(pattern[i + 1:end].split(","))
            i = end + 1
    return ["".join(combo) for combo in itertools.product(*pieces)]


def _translate(pattern):
    """Translate a brace-free pattern into a regex for paths with a "/" appended."""
    # Every segment is matched together with its trailing "/", so "**" can
    # simply match whole segments.
    return "".join(
        "(?:[^/]*/){0,3}" if seg == "**" else
        "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in seg) + "/"
        for seg in pattern.split("/"))


def _matches(rule, rel, is_dir):
    regex, _, dir_only, anchored, _ = rule
    if dir_only and not is_dir:
        return False
    if not anchored:
        rel = rel.rpartition("/")[2]
    return regex.fullmatch(rel + "/") is not None


def _key(name):
    """packignore compared names case-insensitively, up to canonical equivalence."""
    return unicodedata.normalize("NFD", name).casefold()


class _Node:
    def __init__(self, name, is_dir, content=None):
        self.name = name
        self.is_dir = is_dir
        self.content = content
        self.children = {}  # _key(name) -> _Node


def _walk(root):
    """List (path, content) pairs the way packignore was fed them.

    Paths are relative, "/"-separated, in os.walk order; content is the text
    of files named exactly .packignore and None for everything else.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if name == ".packignore":
                with open(full, newline="") as f:
                    yield rel, f.read()
            else:
                yield rel, None


def _build_tree(entries):
    """Build the tree packignore saw: names that differ only in case or
    normalization are one entry, spelled as first seen, with the content of
    the last one seen."""
    root = _Node("", True)
    for rel, content in entries:
        *dirs, name = rel.split("/")
        node = root
        for part in dirs:
            node = node.children.setdefault(_key(part), _Node(part, True))
            if not node.is_dir:
                raise PackignoreError(f"{rel}: a parent is also a file")
        existing = node.children.setdefault(_key(name), _Node(name, False))
        if existing.is_dir:
            raise PackignoreError(f"{rel} is also a directory")
        existing.content = content
    git = root.children.get(_key(".git"))
    if git is not None and git.name == ".git":
        del root.children[_key(".git")]
    return root


def _excluded(rank):
    return rank is not None and not rank[3]


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directly under `root`
    is skipped.

    Raises PackignoreError for trees packignore failed on.
    """
    ignored = []
    # Each entry: (directory node, its path prefix, rank of the pattern
    # deciding it -- (.packignore depth, score, line, negate), or None if none
    # does -- and the [(base prefix, [rule, ...])] in effect for its contents,
    # one entry per .packignore, shallowest first).
    stack = [(_build_tree(_walk(root)), "", None, [])]
    while stack:
        node, prefix, decided, rules = stack.pop()
        excluded = _excluded(decided)
        packignore = node.children.get(_key(".packignore"))
        if packignore is not None and packignore.name == ".packignore" and not excluded:
            if packignore.is_dir:
                raise PackignoreError(f"{prefix}.packignore is a directory")
            # packignore read a .packignore it got no content for as "x".
            text = "x" if packignore.content is None else packignore.content
            rules = rules + [(prefix, [rule for rule in map(_compile, text.splitlines()) if rule])]
        for child in node.children.values():
            path = prefix + child.name
            best = None
            for depth, (base, group) in enumerate(rules):
                for line, rule in enumerate(group):
                    rank = (depth, rule[4], line, rule[1])
                    if (best is None or rank > best) and _matches(rule, path[len(base):], child.is_dir):
                        best = rank
            best = best or decided
            if child.is_dir:
                stack.append((child, path + "/", best, rules))
            elif _excluded(best):
                ignored.append(path)
    return sorted(ignored)
