"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes the format, but the engine's actual rules
differ from it in several ways; this module follows the engine:

- Each line is stripped of surrounding whitespace (str.strip) and lines are
  split with str.splitlines. Blank lines are skipped. There are no comments:
  `#` is an ordinary character, and so is `\\` (there is no escaping).
- A leading `!` negates the pattern. Then trailing `/`s mark a directory-only
  pattern and are removed. A pattern still containing a `/` is anchored to the
  directory holding its .packignore (leading `/`s are dropped); otherwise it
  matches a name at any depth below that directory.
- `{a,b}` alternatives are expanded (no nesting: a group runs from a `{` to
  the next `}`). `**` as a whole segment matches zero to three segments; any
  other run of `*` matches within a segment, and `?` matches one character.
  `[...]` is literal.
- A file is decided by the deepest path, the file itself or else its nearest
  directory, that any pattern matches. Among patterns matching that path, a
  pattern from a deeper .packignore wins; then the more specific pattern (more
  characters other than `*?/{},`); then the later line.
- A .packignore in an excluded directory is not read.
- Names are compared case-insensitively (Unicode caseless matching, as on a
  case-insensitive filesystem). Paths that collide with an earlier one, in
  os.walk order, are merged into it and reported under the earlier spelling.
  Pattern matching itself is case-sensitive, against those spellings.
- A .packignore over 2000 lines, or with a line over 1000 characters, is an
  error, as is a name used for both a file and a directory.
"""

import functools
import itertools
import os
import re
import unicodedata

_BRACES = re.compile(r"\{([^}]*)\}")
_MAX_STAR_STAR = 3  # a `**` segment spans at most this many path segments
_MAX_LINES = 2000
_MAX_LINE_LENGTH = 1000


class PackignoreError(Exception):
    """The tree or a .packignore file is one `packignore` refuses to handle."""


class _Pattern:
    def __init__(self, base, alternatives, negate, dir_only, anchored, rank):
        self.base = base            # directory of the .packignore, as a tuple of segments
        self.alternatives = alternatives
        self.negate = negate
        self.dir_only = dir_only
        self.anchored = anchored
        self.rank = rank            # higher wins among patterns matching the same path

    def matches(self, parts, is_dir):
        if self.dir_only and not is_dir:
            return False
        n = len(self.base)
        if len(parts) <= n or parts[:n] != self.base:
            return False
        rel = parts[n:]
        if self.anchored:
            return any(_match_segments(alt, rel) for alt in self.alternatives)
        return any(alt[0].fullmatch(rel[-1]) for alt in self.alternatives)


@functools.lru_cache(maxsize=4096)
def _segment_regex(seg):
    out = []
    for ch in seg:
        if ch == "*":
            if not out or out[-1] != "[\\s\\S]*":
                out.append("[\\s\\S]*")
        elif ch == "?":
            out.append("[\\s\\S]")
        else:
            out.append(re.escape(ch))
    return re.compile("".join(out))


def _match_segments(pat, parts):
    # pat: tuple of compiled segment regexes, or None for a `**` segment.
    memo = {}

    def go(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(pat):
            r = j == len(parts)
        elif pat[i] is None:
            r = any(go(i + 1, k) for k in range(j, min(j + _MAX_STAR_STAR, len(parts)) + 1))
        else:
            r = j < len(parts) and pat[i].fullmatch(parts[j]) is not None and go(i + 1, j + 1)
        memo[key] = r
        return r

    return go(0, 0)


def _expand(text):
    groups = list(_BRACES.finditer(text))
    if not groups:
        return [text]
    pieces, last = [], 0
    for m in groups:
        pieces.append([text[last:m.start()]])
        pieces.append(m.group(1).split(","))
        last = m.end()
    pieces.append([text[last:]])
    return ["".join(p) for p in itertools.product(*pieces)]


def _parse(text, base, depth):
    patterns = []
    for lineno, line in enumerate(text.splitlines()):
        line = line.strip()
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if not line:
            continue
        score = sum(ch not in "*?/{}," for ch in line)
        alternatives = []
        for alt in _expand(line):
            if anchored:
                alternatives.append(tuple(None if seg == "**" else _segment_regex(seg)
                                          for seg in alt.split("/")))
            else:
                alternatives.append((_segment_regex(alt),))
        patterns.append(_Pattern(base, alternatives, negate, dir_only, anchored,
                                 (depth, score, lineno)))
    return patterns


def _decide(patterns, parts, is_dir):
    """True/False if some pattern matches `parts` itself, else None."""
    best = None
    for p in patterns:
        if (best is None or p.rank >= best.rank) and p.matches(parts, is_dir):
            best = p
    return None if best is None else not best.negate


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            files[rel] = None
            if name == ".packignore":
                with open(full, newline="") as f:
                    files[rel] = f.read()
    return _ignored(files)


def _fold(name):
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


class _Dir:
    def __init__(self, name):
        self.name = name
        self.children = {}  # folded name -> _Dir or _File


class _File:
    def __init__(self, name, text):
        self.name = name
        self.text = text


def _ignored(files):
    """Like ignored_files, given {relative path: .packignore text or None} in os.walk order."""
    for rel, text in files.items():
        if text is not None:
            lines = text.splitlines()
            if len(lines) > _MAX_LINES or any(len(line) > _MAX_LINE_LENGTH for line in lines):
                raise PackignoreError(f"{rel}: ignore file too large (limits: {_MAX_LINES} lines, "
                                      f"{_MAX_LINE_LENGTH} characters per line)")

    # Build the tree case-insensitively: the first spelling of a name is kept,
    # while a later file with the same name replaces the earlier one's contents.
    root = _Dir("")
    for rel, text in files.items():
        *dirs, name = rel.split("/")
        node = root
        for d in dirs:
            child = node.children.setdefault(_fold(d), _Dir(d))
            if not isinstance(child, _Dir):
                raise PackignoreError(f"{rel}: {child.name!r} is both a file and a directory")
            node = child
        child = node.children.get(_fold(name))
        if child is None:
            node.children[_fold(name)] = _File(name, text)
        elif isinstance(child, _Dir):
            raise PackignoreError(f"{rel}: {child.name!r} is both a file and a directory")
        else:
            child.text = text

    ignored = []
    stack = [((), root, False, [])]  # (path, directory, excluded, patterns from its ancestors)
    while stack:
        dir_parts, node, excluded, patterns = stack.pop()
        if not excluded:
            f = node.children.get(_fold(".packignore"))
            if isinstance(f, _File) and f.name == ".packignore" and f.text is not None:
                patterns = patterns + _parse(f.text, dir_parts, len(dir_parts))
        for child in node.children.values():
            parts = dir_parts + (child.name,)
            is_dir = isinstance(child, _Dir)
            state = _decide(patterns, parts, is_dir)
            if state is None:
                state = excluded
            if is_dir:
                stack.append((parts, child, state, patterns))
            elif state:
                ignored.append("/".join(parts))
    return sorted(ignored)
