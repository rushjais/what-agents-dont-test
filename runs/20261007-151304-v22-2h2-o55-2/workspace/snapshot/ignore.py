"""Decide which files in a project tree are excluded by its .packignore files.

A pure-Python reimplementation of `packignore`, the legacy exclusion engine,
matching its output exactly. The rules, including its many quirks, are
described in docs/PACKIGNORE.md.
"""

import os
import re
import stat
import unicodedata

_PACKIGNORE = ".packignore"
_MAX_LINES = 2000
_MAX_LINE_LENGTH = 1000
_MAX_FILES = 5000
_MAX_DEPTH = 64
_MAX_PATH_BYTES = 955  # longer relative paths made packignore fail
_NOT_SCORED = set("*?/{},")


class PackignoreError(Exception):
    """The tree cannot be evaluated (packignore reported an internal error)."""


class _Pattern:
    __slots__ = ("negated", "dir_only", "anchored", "score", "_match")

    def __init__(self, negated, dir_only, anchored, score, match):
        self.negated = negated
        self.dir_only = dir_only
        self.anchored = anchored
        self.score = score
        self._match = match

    def matches(self, rel, is_dir):
        if self.dir_only and not is_dir:
            return False
        return self._match(rel if self.anchored else rel.rsplit("/", 1)[-1])


def _brace_pieces(pat):
    """Split a pattern into literal strings and `{a,b}` groups (lists).

    Each group runs from a `{` to the first `}` after it; groups do not nest
    and an unclosed `{` is literal.
    """
    pieces = []
    while True:
        i = pat.find("{")
        j = pat.find("}", i + 1) if i >= 0 else -1
        if j < 0:
            pieces.append(pat)
            return pieces
        pieces.append(pat[:i])
        pieces.append(pat[i + 1:j].split(","))
        pat = pat[j + 1:]


def _expand_braces(pieces):
    out = [""]
    for piece in pieces:
        alts = piece if isinstance(piece, list) else [piece]
        out = [s + a for s in out for a in alts]
    return out


def _translate_glob(pat, anchored):
    """Translate a brace-free glob into a regular expression string."""
    out = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            j = i
            while j < n and pat[j] == "*":
                j += 1
            if (anchored and j - i == 2 and (i == 0 or pat[i - 1] == "/")
                    and (j == n or pat[j] == "/")):
                if j < n:
                    out.append("(?:.*/)?")
                    j += 1  # the slash is part of the optional group
                elif out and out[-1] == "/":
                    out[-1] = "(?:/.*)?"
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
            i = j
            continue
        out.append("[^/]" if c == "?" else re.escape(c))
        i += 1
    return "".join(out)


# Contexts for _GlobMatcher: what precedes the current run of stars.
_BOUNDARY, _SLASH, _OTHER = 0, 1, 2


class _GlobMatcher:
    """Match a braced glob without expanding it.

    Equivalent to fully matching the alternation of `_translate_glob` over
    every brace expansion, but the number of expansions can be huge. The
    search walks the pattern pieces directly, carrying the context the
    translation depends on: the run of `*`s so far (capped at 3), and whether
    it follows the start of the pattern or a slash that a `**/` consumed
    (_BOUNDARY), a plain `/` not yet matched (_SLASH), or anything else.
    """

    def __init__(self, pieces, anchored):
        self.strings = [p if isinstance(p, list) else [p] for p in pieces]
        self.anchored = anchored

    def _next(self, k, a, o):
        """Yield the pattern positions (k, a, o) holding the next character."""
        if o < len(self.strings[k][a]):
            yield (k, a, o)
            return
        k += 1
        if k == len(self.strings):
            yield None
            return
        for a2 in range(len(self.strings[k])):
            yield from self._next(k, a2, 0)

    def __call__(self, path):
        n = len(path)
        seen = set()
        stack = [(pos, _BOUNDARY, 0, 0) for pos in self._next(0, 0, 0)]
        while stack:
            state = stack.pop()
            if state in seen:
                continue
            seen.add(state)
            pos, prev, run, i = state
            globstar = self.anchored and run == 2 and prev != _OTHER
            if pos is None:
                if globstar:
                    if prev == _BOUNDARY or i == n or path[i] == "/":
                        return True
                    continue
                if prev == _SLASH:
                    if i == n or path[i] != "/":
                        continue
                    i += 1
                if (path.find("/", i) < 0) if run else i == n:
                    return True
                continue
            k, a, o = pos
            c = self.strings[k][a][o]
            after = list(self._next(k, a, o + 1))
            if c == "*":
                stack.extend((p, prev, min(run + 1, 3), i) for p in after)
                continue
            if prev == _SLASH:
                if i == n or path[i] != "/":
                    continue
                i += 1
            if globstar and c == "/":
                starts = [i] + [j + 1 for j in range(i, n) if path[j] == "/"]
                stack.extend((p, _BOUNDARY, 0, j) for j in starts for p in after)
                continue
            if run:
                stop = path.find("/", i)
                starts = range(i, (n if stop < 0 else stop) + 1)
            else:
                starts = (i,)
            for j in starts:
                if c == "/":
                    stack.extend((p, _SLASH, 0, j) for p in after)
                elif j < n and (path[j] != "/" if c == "?" else path[j] == c):
                    stack.extend((p, _OTHER, 0, j + 1) for p in after)
        return False


# Brace expansions up to this many alternatives are compiled into one regex.
_MAX_EXPANSIONS = 256


def _compile(pat, anchored):
    pieces = _brace_pieces(pat)
    count = 1
    for piece in pieces:
        if isinstance(piece, list):
            count *= len(piece)
    if count > _MAX_EXPANSIONS:
        return _GlobMatcher(pieces, anchored)
    alts = dict.fromkeys(_translate_glob(alt, anchored) for alt in _expand_braces(pieces))
    regex = re.compile("(?:" + "|".join(alts) + ")", re.DOTALL)
    return lambda s: regex.fullmatch(s) is not None


def _parse_line(line):
    line = line.strip()
    if not line or line.startswith(";"):
        return None
    negated = line.startswith("!")
    pat = line[1:] if negated else line
    score = sum(1 for c in pat if c not in _NOT_SCORED)
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    anchored = "/" in pat
    pat = pat.lstrip("/")
    if not pat:
        return None
    return _Pattern(negated, dir_only, anchored, score, _compile(pat, anchored))


def _parse(data, path):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PackignoreError(f"{path}: {e}") from None
    return [p for p in map(_parse_line, text.splitlines()) if p is not None]


def _fold(name):
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


class _Dir:
    __slots__ = ("name", "dirs", "files")

    def __init__(self, name):
        self.name = name
        self.dirs = {}   # folded name -> _Dir
        self.files = {}  # folded name -> [name, full path, mode]


def _scan(root):
    """Build the caseless tree of regular files under `root`."""
    top = _Dir("")
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            parts = rel.split("/")
            count += 1
            if count > _MAX_FILES:
                raise PackignoreError(f"too many files (limit {_MAX_FILES})")
            if len(parts) > _MAX_DEPTH:
                raise PackignoreError(f"{rel}: path too deep (limit {_MAX_DEPTH} levels)")
            if len(rel.encode("utf-8", "surrogateescape")) > _MAX_PATH_BYTES:
                raise PackignoreError(f"{rel}: path too long (limit {_MAX_PATH_BYTES} bytes)")
            node = top
            for part in parts[:-1]:
                key = _fold(part)
                if key in node.files:
                    raise PackignoreError(f"{full}: file/directory name collision")
                node = node.dirs.setdefault(key, _Dir(part))
            key = _fold(parts[-1])
            if key in node.dirs:
                raise PackignoreError(f"{full}: file/directory name collision")
            mode = os.stat(full).st_mode
            if key in node.files:
                entry = node.files[key]
                entry[1], entry[2] = full, mode
            else:
                node.files[key] = [parts[-1], full, mode]
    return top


def _check_limits(node):
    """Every .packignore in the tree, read or not, must be within the limits."""
    for name, full, _ in node.files.values():
        if name == _PACKIGNORE:
            with open(full, "rb") as f:
                lines = f.read().decode("utf-8", "replace").splitlines()
            if len(lines) > _MAX_LINES or any(len(line) > _MAX_LINE_LENGTH for line in lines):
                raise PackignoreError(f"{full}: ignore file too large (limits: {_MAX_LINES} "
                                      f"lines, {_MAX_LINE_LENGTH} characters per line)")
    for child in node.dirs.values():
        _check_limits(child)


def _implicitly_ignored(full, mode):
    """Executable files, and files whose first line contains "@generated"."""
    if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        return True
    marker = b"@generated"
    tail = b""
    with open(full, "rb") as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                return False
            line = tail + chunk.split(b"\n", 1)[0]
            if marker in line:
                return True
            if b"\n" in chunk:
                return False
            tail = line[-(len(marker) - 1):]


def _match_level(parts, level, is_dir, rules):
    """Return the winning pattern for the path `parts[:level]`, or None.

    `rules` lists (depth, patterns) for the .packignore files that apply,
    where depth is the number of path components of the directory holding
    the file; a file only applies to paths strictly below its directory.
    """
    best = best_key = None
    for depth, patterns in rules:
        if depth >= level:
            continue
        rel = "/".join(parts[depth:level])
        for idx, p in enumerate(patterns):
            if p.matches(rel, is_dir):
                key = (depth, p.score, idx)
                if best_key is None or key > best_key:
                    best, best_key = p, key
    return best


def _excluded(parts, is_dir, rules, implicit=None):
    """Decide whether the file or directory `parts` is excluded.

    The deepest level (the path itself, then each ancestor) that a pattern
    matches decides. For a file, `implicit()` is consulted when no pattern
    matches the file itself, before falling back to its directories.
    """
    for level in range(len(parts), 0, -1):
        p = _match_level(parts, level, is_dir or level < len(parts), rules)
        if p is not None:
            return not p.negated
        if implicit is not None and level == len(parts) and implicit():
            return True
    return False


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    result = []

    def visit(node, parts, rules, excluded):
        if not excluded:
            pi = next((e for e in node.files.values() if e[0] == _PACKIGNORE), None)
            if pi is not None:
                with open(pi[1], "rb") as f:
                    rules = rules + [(len(parts), _parse(f.read(), pi[1]))]
            elif any(d.name == _PACKIGNORE for d in node.dirs.values()):
                raise PackignoreError("/".join(parts + [_PACKIGNORE]) + " is a directory")
        for name, full, mode in node.files.values():
            if not parts and name == ".git":
                continue  # never reported, like the skipped .git directory
            path = parts + [name]
            if _excluded(path, False, rules, lambda: _implicitly_ignored(full, mode)):
                result.append("/".join(path))
        for child in node.dirs.values():
            path = parts + [child.name]
            visit(child, path, rules, _excluded(path, True, rules))

    top = _scan(root)
    _check_limits(top)
    visit(top, [], [], False)
    return sorted(result)
