"""Decide which files in a project tree are excluded by its .packignore files.

A pure-Python reimplementation of `packignore`, the legacy exclusion engine.
docs/PACKIGNORE.md describes the syntax but is out of date; the rules below
are the ones `packignore` actually applies.

Syntax (one pattern per line):

- Lines are stripped of surrounding whitespace. Blank lines are skipped and
  lines starting with `;` are comments (`#` is an ordinary character).
- A leading `!` re-includes. It is not followed by any further stripping.
- `*` matches any run of characters within a path segment, `?` exactly one.
  A segment that is exactly `**` matches zero to three whole segments; `**`
  inside a longer segment behaves like `*`. Every other character, including
  `[`, `]` and `\\`, is literal.
- A trailing `/` makes the pattern match directories only. A leading `/` is
  dropped. If what remains contains a `/`, the pattern is matched against
  the path relative to the .packignore's directory; otherwise against the
  name alone, at any depth.

Precedence:

- Every directory on a file's path, and the file itself, is a "level". The
  deepest level that any pattern matches decides; excluding a directory
  excludes its contents unless something deeper re-includes them.
- Within a level, the deepest .packignore with a matching pattern decides.
- Within a .packignore, the most specific matching pattern decides, where
  specificity is the number of characters other than `*`, `?` and `/`.
  Ties go to the later line.
- A .packignore is only read if its own directory is not excluded.
"""

import functools
import os
import re
import unicodedata

_NAME = ".packignore"
_MAX_GLOBSTAR = 3  # a `**` segment matches at most this many segments


class _Rule:
    __slots__ = ("negate", "dir_only", "anchored", "segments", "regex", "specificity")

    def __init__(self, negate, dir_only, anchored, body):
        self.negate = negate
        self.dir_only = dir_only
        self.specificity = sum(1 for c in body if c not in "*?/")
        self.anchored = anchored
        if self.anchored:
            self.segments = tuple(None if s == "**" else _segment_regex(s) for s in body.split("/"))
            self.regex = None
        else:
            self.segments = None
            self.regex = _segment_regex(body)

    def matches(self, parts, is_dir):
        """`parts`: the path segments relative to the .packignore's directory."""
        if self.dir_only and not is_dir:
            return False
        if not self.anchored:
            return self.regex.fullmatch(parts[-1]) is not None
        return _match_segments(self.segments, tuple(parts))


@functools.lru_cache(maxsize=None)
def _segment_regex(seg):
    out = []
    for tok in re.split(r"(\*+|\?)", seg):
        if not tok:
            continue
        if tok[0] == "*":
            out.append(".*")
        elif tok == "?":
            out.append(".")
        else:
            out.append(re.escape(tok))
    return re.compile("".join(out), re.DOTALL)


def _match_segments(pat, parts):
    @functools.lru_cache(maxsize=None)
    def go(i, j):
        if i == len(pat):
            return j == len(parts)
        if pat[i] is None:
            return any(go(i + 1, k) for k in range(j, min(j + _MAX_GLOBSTAR, len(parts)) + 1))
        return j < len(parts) and pat[i].fullmatch(parts[j]) is not None and go(i + 1, j + 1)

    return go(0, 0)


def _parse(text):
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        body = line.lstrip("/")
        if not body:
            continue
        rules.append(_Rule(negate, dir_only, "/" in line, body))
    return rules


class PackignoreError(Exception):
    """A tree that `packignore` rejects (it fails with "internal error")."""


def _read_rules(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackignoreError(f"{path}: not valid UTF-8") from None
    return _parse(text)


def _fold(name):
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def _list_files(root):
    """The files `packignore` sees under `root`.

    Returns a dict mapping each file, as a tuple of segments, to the full
    path its contents come from.

    Only regular files are seen (no symlinks), in os.walk order. Names are
    case- and normalization-insensitive: paths that differ only that way are
    merged under the spelling seen first, and the contents seen last win.
    """
    files = {}
    canon = {}  # (canonical parent, folded name) -> (canonical name, is_dir)
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        rel = os.path.relpath(dirpath, root)
        prefix = () if rel == os.curdir else tuple(rel.split(os.sep))
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            parts = prefix + (name,)
            try:
                "/".join(parts).encode("utf-8")
            except UnicodeEncodeError:
                raise PackignoreError(f"{full}: name is not valid UTF-8") from None
            path = ()
            for i, seg in enumerate(parts):
                is_dir = i < len(parts) - 1
                key = (path, _fold(seg))
                seg, was_dir = canon.setdefault(key, (seg, is_dir))
                if was_dir != is_dir:
                    raise PackignoreError(f"{full}: file and directory names collide")
                path += (seg,)
            files[path] = full
    return files


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    files = _list_files(root)
    dirs = {f[:i] for f in files for i in range(1, len(f))}
    rules = {}  # directory (tuple) -> rules of its .packignore, if read
    excluded = {}  # directory (tuple) -> whether it is excluded

    def level_decision(path, is_dir):
        """True/False if some pattern matches `path` itself, else None."""
        for depth in range(len(path) - 1, -1, -1):
            dir_rules = rules_for(path[:depth])
            if not dir_rules:
                continue
            rel = path[depth:]
            best = None
            for rule in dir_rules:
                if (best is None or rule.specificity >= best.specificity) and rule.matches(rel, is_dir):
                    best = rule
            if best is not None:
                return not best.negate
        return None

    def rules_for(d):
        if d not in rules:
            path = d + (_NAME,)
            if d and is_excluded(d) or path not in files and path not in dirs:
                rules[d] = None
            elif path in dirs:
                raise PackignoreError(f"{os.path.join(root, *path)}: is a directory")
            else:
                rules[d] = _read_rules(files[path])
        return rules[d]

    def is_excluded(d):
        if d not in excluded:
            decision = level_decision(d, True)
            if decision is None:
                decision = bool(d[:-1]) and is_excluded(d[:-1])
            excluded[d] = decision
        return excluded[d]

    out = []
    for f in files:
        decision = level_decision(f, False)
        if decision is None:
            decision = len(f) > 1 and is_excluded(f[:-1])
        if decision:
            out.append("/".join(f))
    return sorted(out)
