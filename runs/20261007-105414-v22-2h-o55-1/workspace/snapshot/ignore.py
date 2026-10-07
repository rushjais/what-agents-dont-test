"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes the intent; the rules below are what the
engine actually did, quirks included:

* `.packignore` files are UTF-8, split into lines like `str.splitlines()`,
  and each line is stripped of surrounding whitespace. Lines starting with
  `;` are comments (`#` is an ordinary character). Only `*`, `?`, `**` (as a
  whole path segment, standing for at most three segments) and `{a,b}` are
  special; backslashes and brackets are literal. A brace group runs from a
  `{` to the next `}`, with no nesting.
* `!`, a trailing `/` (directories only) and anchoring (the pattern contains
  a `/`) are decided before braces are expanded.
* Patterns are checked against every level of a file's path: each ancestor
  directory, then the file. The deepest level that any pattern matches
  decides. At one level, the deepest `.packignore` with a matching pattern
  decides; within it, the most specific matching pattern wins (most literal
  characters, see `_specificity`), and among equally specific ones the last.
* A `.packignore` inside an excluded directory is not read.
* Executable files (any execute bit) and files whose first line contains
  `@generated` are excluded, unless a `!pattern` matches the file itself.
* The engine stored the tree on a case- and normalization-insensitive
  filesystem: paths that differ only in case or Unicode normalization are one
  file, named after the first one uploaded but with the last one's contents.

Trees the engine rejected (a file and a directory with the same folded path,
a directory named `.packignore`, a non-UTF-8 file name or `.packignore`)
raise `PackignoreError`.
"""

import os
import re
import unicodedata

IGNORE_FILE = ".packignore"


class PackignoreError(Exception):
    """packignore would have rejected this tree."""


def _fold(name):
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


class _Node:
    __slots__ = ("name", "children", "is_dir", "path")

    def __init__(self, name, is_dir, path):
        self.name = name
        self.is_dir = is_dir
        self.path = path  # real path of the (last) source file, for files
        self.children = {} if is_dir else None


def _build_tree(root):
    """Mirror how the engine stored the uploaded tree."""
    top = _Node("", True, None)
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            try:
                rel.encode("utf-8")
            except UnicodeEncodeError:
                raise PackignoreError(f"file name is not UTF-8: {rel!r}") from None
            parts = rel.split("/")
            node = top
            for part in parts[:-1]:
                key = _fold(part)
                child = node.children.get(key)
                if child is None:
                    child = node.children[key] = _Node(part, True, None)
                elif not child.is_dir:
                    raise PackignoreError(f"{rel!r} collides with a file")
                node = child
            key = _fold(parts[-1])
            child = node.children.get(key)
            if child is None:
                node.children[key] = _Node(parts[-1], False, full)
            elif child.is_dir:
                raise PackignoreError(f"{rel!r} collides with a directory")
            else:
                child.path = full
    return top


# The engine let each `**` stand for at most this many path segments.
_GLOBSTAR_MAX = 3


def _translate(pat, inline):
    """Translate a glob (no leading or trailing "/") into a regex string.
    `inline` maps placeholder characters to ready-made regexes."""
    segs = pat.split("/")
    if all(seg == "**" for seg in segs):
        return "[^/]+(?:/[^/]+){0,%d}" % (_GLOBSTAR_MAX * len(segs) - 1)
    out = []
    need_sep = False
    for seg in segs:
        if seg == "**":
            out.append("(?:/[^/]+){0,%d}" % _GLOBSTAR_MAX if need_sep
                       else "(?:[^/]+/){0,%d}" % _GLOBSTAR_MAX)
            continue
        if need_sep:
            out.append("/")
        need_sep = True
        for ch in re.sub(r"\*+", "*", seg):
            if ch == "*":
                out.append("[^/]*")
            elif ch == "?":
                out.append("[^/]")
            elif ch in inline:
                out.append(inline[ch])
            else:
                out.append(re.escape(ch))
    return "".join(out)


def _expand_braces(pat):
    """Expand `{a,b}` groups: each runs from a `{` to the next `}`, with no
    nesting, and text produced by a group is never expanded again."""
    i = pat.find("{")
    j = pat.find("}", i + 1) if i >= 0 else -1
    if j < 0:
        return [pat]
    rest = _expand_braces(pat[j + 1:])
    return [pat[:i] + alt + tail for alt in pat[i + 1:j].split(",") for tail in rest]


def _inline_braces(pat):
    """Replace brace groups that can't change the shape of a pattern (no
    `/`, no `*`, no empty alternative) with placeholder characters standing
    for a regex alternation, so they don't multiply the expansions."""
    spare = (chr(c) for c in range(0xE000, 0xF900) if chr(c) not in pat)
    inline = {}
    out = []
    pos = 0
    while True:
        i = pat.find("{", pos)
        j = pat.find("}", i + 1) if i >= 0 else -1
        if j < 0:
            break
        alts = pat[i + 1:j].split(",")
        if all(alt and "/" not in alt and "*" not in alt for alt in alts):
            ph = next(spare)
            inline[ph] = "(?:%s)" % "|".join(
                "".join("[^/]" if ch == "?" else re.escape(ch) for ch in alt) for alt in alts)
            out.append(pat[pos:i] + ph)
        else:
            out.append(pat[pos:j + 1])
        pos = j + 1
    out.append(pat[pos:])
    return "".join(out), inline


def _specificity(pat):
    """How specific a pattern is: the number of characters other than
    `*`, `?`, `/`, `{`, `}` and `,`."""
    return sum(ch not in "*?/{}," for ch in pat)


class _Pattern:
    __slots__ = ("negate", "dir_only", "anchored", "regex", "score")

    def __init__(self, line):
        self.negate = line.startswith("!")
        if self.negate:
            line = line[1:]
        self.score = _specificity(line)
        self.dir_only = line.endswith("/")
        line = line.rstrip("/")
        self.anchored = "/" in line
        stripped = line.lstrip("/")
        stripped, inline = _inline_braces(stripped)
        alts = dict.fromkeys(_translate(a, inline) for a in _expand_braces(stripped) if a)
        self.regex = re.compile("|".join(alts), re.S) if alts else None

    def matches(self, rel, base, is_dir):
        if self.regex is None or (self.dir_only and not is_dir):
            return False
        return self.regex.fullmatch(rel if self.anchored else base) is not None


def _parse(data, path):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PackignoreError(f"{path!r} is not UTF-8: {e}") from None
    pats = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        pats.append(_Pattern(line))
    return pats


def _decide(rules, rel, is_dir):
    """rules: list of (prefix, patterns), shallowest first. Return True
    (excluded), False (re-included) or None (no match)."""
    base = rel.rsplit("/", 1)[-1]
    for prefix, pats in reversed(rules):
        sub = rel[len(prefix):]
        best = None
        for p in pats:
            if p.matches(sub, base, is_dir) and (best is None or p.score >= best.score):
                best = p
        if best is not None:
            return not best.negate
    return None


def _builtin_excluded(path):
    """Executable, or `@generated` on the first line."""
    if os.stat(path).st_mode & 0o111:
        return True
    first = b""
    with open(path, "rb") as f:
        while b"\n" not in first:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            first += chunk
    return b"@generated" in first.split(b"\n", 1)[0]


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    result = []
    stack = [(_build_tree(root), "", [], False)]
    while stack:
        node, prefix, rules, excluded = stack.pop()
        ign = node.children.get(_fold(IGNORE_FILE))
        if not excluded and ign is not None and ign.name == IGNORE_FILE:
            if ign.is_dir:
                raise PackignoreError(f"{prefix + IGNORE_FILE!r} is a directory")
            with open(ign.path, "rb") as f:
                pats = _parse(f.read(), prefix + IGNORE_FILE)
            if pats:
                rules = rules + [(prefix, pats)]
        for child in node.children.values():
            rel = prefix + child.name
            if child.is_dir:
                d = _decide(rules, rel, True)
                stack.append((child, rel + "/", rules, excluded if d is None else d))
            else:
                d = _decide(rules, rel, False)
                if d is None:
                    d = excluded or _builtin_excluded(child.path)
                if d:
                    result.append(rel)

    # packignore reported one path per line, so names containing line breaks
    # came back split into pieces.
    return sorted(line for line in "\n".join(result).splitlines() if line)
