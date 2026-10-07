"""Decide which files in a project tree are ignored by its .gitignore files.

This is a pure-Python reimplementation of what
`git ls-files --others --ignored --exclude-standard` reports for an untracked
tree, with `core.ignorecase=false` and no global or per-repository excludes
files. It follows git's dir.c and wildmatch.c closely (including their quirks)
so that the answer is the same as git's.
"""

import os
import stat

# Pattern flags (dir.c).
_NODIR = 1
_ENDSWITH = 4
_MUSTBEDIR = 8
_NEGATIVE = 16

# git refuses to read pattern files larger than this (PATTERN_MAX_FILE_SIZE).
_MAX_FILE_SIZE = 100 * 1024 * 1024

_GLOB_SPECIAL = frozenset(b"*?[\\")


def _simple_length(p):
    """Length of the leading run of `p` without glob special characters."""
    for i, c in enumerate(p):
        if c in _GLOB_SPECIAL:
            return i
    return len(p)


# ---------------------------------------------------------------------------
# wildmatch (a direct port of git's wildmatch.c, without WM_CASEFOLD)

_WM_MATCH = 0
_WM_NOMATCH = 1
_WM_ABORT_ALL = -1
_WM_ABORT_TO_STARSTAR = -2

_SLASH, _STAR, _QMARK, _BSLASH = ord("/"), ord("*"), ord("?"), ord("\\")
_LBRACKET, _RBRACKET, _COLON, _DASH = ord("["), ord("]"), ord(":"), ord("-")
_BANG, _CARET = ord("!"), ord("^")


def _range(lo, hi):
    return frozenset(range(ord(lo), ord(hi) + 1))


_UPPER = _range("A", "Z")
_LOWER = _range("a", "z")
_ALPHA = _UPPER | _LOWER
_DIGIT = _range("0", "9")
_PRINT = frozenset(range(0x20, 0x7F))
# git's own ctype table: only \t, \n, \r and space are whitespace.
_SPACE = frozenset(b" \t\n\r")

_CLASSES = {
    b"alnum": _ALPHA | _DIGIT,
    b"alpha": _ALPHA,
    b"blank": frozenset(b" \t"),
    b"cntrl": frozenset(range(0x20)) | {0x7F},
    b"digit": _DIGIT,
    b"graph": frozenset(range(0x21, 0x7F)),
    b"lower": _LOWER,
    b"print": _PRINT,
    b"punct": _PRINT - _ALPHA - _DIGIT - {0x20},
    b"space": _SPACE,
    b"upper": _UPPER,
    b"xdigit": _DIGIT | _range("a", "f") | _range("A", "F"),
}


def _dowild(p, pi, t, ti, pathname):
    """Match p[pi:] against t[ti:]; p[0] is the start of the pattern."""
    plen, tlen = len(p), len(t)

    def pat(i):
        return p[i] if i < plen else 0

    while pi < plen:
        p_ch = p[pi]
        t_ch = t[ti] if ti < tlen else 0
        if t_ch == 0 and p_ch != _STAR:
            return _WM_ABORT_ALL

        if p_ch == _QMARK:
            if pathname and t_ch == _SLASH:
                return _WM_NOMATCH

        elif p_ch == _STAR:
            pi += 1
            if pat(pi) == _STAR:
                prev_p = pi - 2
                pi += 1
                while pat(pi) == _STAR:
                    pi += 1
                c = pat(pi)
                if ((prev_p < 0 or p[prev_p] == _SLASH) and
                        (c == 0 or c == _SLASH or (c == _BSLASH and pat(pi + 1) == _SLASH))):
                    if c == _SLASH and _dowild(p, pi + 1, t, ti, pathname) == _WM_MATCH:
                        return _WM_MATCH
                    match_slash = True
                else:
                    match_slash = False
            else:
                match_slash = not pathname

            c = pat(pi)
            if c == 0:
                # Trailing "**" matches everything; trailing "*" matches
                # only if there are no more slashes.
                if not match_slash and t.find(b"/", ti) >= 0:
                    return _WM_NOMATCH
                return _WM_MATCH
            if not match_slash and c == _SLASH:
                # A single "*" followed by "/" matches the next directory.
                slash = t.find(b"/", ti)
                if slash < 0:
                    return _WM_NOMATCH
                ti = slash + 1
                pi += 1
                continue

            while True:
                if t_ch == 0:
                    break
                if c not in _GLOB_SPECIAL:
                    # Skip ahead to the next occurrence of the literal.
                    while True:
                        t_ch = t[ti] if ti < tlen else 0
                        if t_ch == 0 or (not match_slash and t_ch == _SLASH):
                            break
                        if t_ch == c:
                            break
                        ti += 1
                    if t_ch != c:
                        return _WM_ABORT_ALL if match_slash else _WM_ABORT_TO_STARSTAR
                matched = _dowild(p, pi, t, ti, pathname)
                if matched != _WM_NOMATCH:
                    if not match_slash or matched != _WM_ABORT_TO_STARSTAR:
                        return matched
                elif not match_slash and t_ch == _SLASH:
                    return _WM_ABORT_TO_STARSTAR
                ti += 1
                t_ch = t[ti] if ti < tlen else 0
            return _WM_ABORT_ALL

        elif p_ch == _LBRACKET:
            pi += 1
            p_ch = pat(pi)
            if p_ch == _CARET:
                p_ch = _BANG
            negated = p_ch == _BANG
            if negated:
                pi += 1
                p_ch = pat(pi)
            prev_ch = 0
            matched = False
            while True:
                if not p_ch:
                    return _WM_ABORT_ALL
                if p_ch == _BSLASH:
                    pi += 1
                    p_ch = pat(pi)
                    if not p_ch:
                        return _WM_ABORT_ALL
                    if t_ch == p_ch:
                        matched = True
                elif p_ch == _DASH and prev_ch and pat(pi + 1) and pat(pi + 1) != _RBRACKET:
                    pi += 1
                    p_ch = pat(pi)
                    if p_ch == _BSLASH:
                        pi += 1
                        p_ch = pat(pi)
                        if not p_ch:
                            return _WM_ABORT_ALL
                    if prev_ch <= t_ch <= p_ch:
                        matched = True
                    p_ch = 0  # so that prev_ch becomes 0
                elif p_ch == _LBRACKET and pat(pi + 1) == _COLON:
                    pi += 2
                    s = pi
                    while pat(pi) and pat(pi) != _RBRACKET:
                        pi += 1
                    p_ch = pat(pi)
                    if not p_ch:
                        return _WM_ABORT_ALL
                    n = pi - s - 1
                    if n < 0 or p[pi - 1] != _COLON:
                        # No ":]", so treat it like a normal set.
                        pi = s - 2
                        p_ch = _LBRACKET
                        if t_ch == p_ch:
                            matched = True
                    else:
                        members = _CLASSES.get(p[s:s + n])
                        if members is None:
                            return _WM_ABORT_ALL  # malformed [:class:]
                        if t_ch in members:
                            matched = True
                        p_ch = 0
                elif t_ch == p_ch:
                    matched = True
                prev_ch = p_ch
                pi += 1
                p_ch = pat(pi)
                if p_ch == _RBRACKET:
                    break
            if matched == negated or (pathname and t_ch == _SLASH):
                return _WM_NOMATCH

        else:
            if p_ch == _BSLASH:
                # Literal match with the following character.
                pi += 1
                p_ch = pat(pi)
            if t_ch != p_ch:
                return _WM_NOMATCH

        pi += 1
        ti += 1

    return _WM_NOMATCH if ti < tlen else _WM_MATCH


def _wildmatch(pattern, text, pathname):
    return _dowild(pattern, 0, text, 0, pathname) == _WM_MATCH


# ---------------------------------------------------------------------------
# Patterns (dir.c)

class _Pattern:
    __slots__ = ("pattern", "nowildcardlen", "flags", "base")

    def __init__(self, line, base):
        flags = 0
        p = line
        if p[:1] == b"!":
            flags |= _NEGATIVE
            p = p[1:]
        length = len(p)
        if length and p[-1] == _SLASH:
            length -= 1
            flags |= _MUSTBEDIR
        if b"/" not in p[:length]:
            flags |= _NODIR
        self.nowildcardlen = min(_simple_length(p), length)
        if p[:1] == b"*" and _simple_length(p[1:]) == len(p) - 1:
            flags |= _ENDSWITH
        self.pattern = p[:length]
        self.flags = flags
        self.base = base  # directory of the .gitignore, "" or ending in "/"


def _trim_trailing_spaces(buf):
    last_space = None
    i, n = 0, len(buf)
    while i < n:
        c = buf[i]
        if c == 0x20:
            if last_space is None:
                last_space = i
        elif c == _BSLASH:
            i += 1
            if i >= n:
                return buf
            last_space = None
        else:
            last_space = None
        i += 1
    return buf if last_space is None else buf[:last_space]


def _parse_gitignore(buf, base):
    if buf.startswith(b"\xef\xbb\xbf"):
        buf = buf[3:]
    patterns = []
    lines = buf.split(b"\n")
    # git appends a newline to the file, so the text after the last "\n"
    # is a line too (possibly empty).
    for line in lines:
        if not line or line[0] == ord("#"):
            continue
        if line[-1] == ord("\r"):
            line = line[:-1]
        nul = line.find(b"\0")
        if nul >= 0:
            line = line[:nul]
        patterns.append(_Pattern(_trim_trailing_spaces(line), base))
    return patterns


def _read_gitignore(path, base):
    # git opens per-directory .gitignore files with O_NOFOLLOW.
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return []
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size == 0 or st.st_size > _MAX_FILE_SIZE:
            return []
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        return []
    finally:
        os.close(fd)
    return _parse_gitignore(b"".join(chunks), base)


def _match_basename(basename, pat):
    pattern = pat.pattern
    if pat.nowildcardlen == len(pattern):
        return pattern == basename
    if pat.flags & _ENDSWITH:
        return basename.endswith(pattern[1:])
    return _wildmatch(pattern, basename, False)


def _match_pathname(pathname, pat):
    pattern = pat.pattern
    prefix = pat.nowildcardlen
    if pattern[:1] == b"/":
        pattern = pattern[1:]
        prefix -= 1

    base = pat.base
    if base:
        if not pathname.startswith(base) or len(pathname) == len(base):
            return False
        name = pathname[len(base):]
    else:
        if not pathname:
            return False
        name = pathname

    if prefix:
        if prefix > len(name) or pattern[:prefix] != name[:prefix]:
            return False
        pattern = pattern[prefix:]
        name = name[prefix:]
        if not pattern and not name:
            return True

    return _wildmatch(pattern, name, True)


def _is_excluded(path, is_dir, patterns):
    """Whether `path` (bytes, relative to the root) is ignored by `patterns`."""
    basename = path[path.rfind(b"/") + 1:]
    for pat in reversed(patterns):
        flags = pat.flags
        if flags & _MUSTBEDIR and not is_dir:
            continue
        if flags & _NODIR:
            hit = _match_basename(basename, pat)
        else:
            hit = _match_pathname(path, pat)
        if hit:
            return not flags & _NEGATIVE
    return False


# ---------------------------------------------------------------------------
# Directory traversal

def _entries(dirpath):
    """(name, kind) for the entries git looks at; kind is "dir" or "file"."""
    try:
        with os.scandir(dirpath) as it:
            entries = list(it)
    except OSError:
        return []
    out = []
    for e in entries:
        # git skips anything called ".git", at any depth.
        if e.name == ".git":
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                out.append((e.name, "dir"))
            elif e.is_file(follow_symlinks=False) or e.is_symlink():
                out.append((e.name, "file"))
            # Sockets, FIFOs, devices: git ignores them.
        except OSError:
            continue
    return out


def ignored_files(root):
    """Return the files under `root` that its .gitignore files ignore.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. Only .gitignore files inside
    `root` are consulted; a `.git` directory directly under `root` is skipped.
    """
    result = []

    def add_all(dirpath, rel):
        # Everything inside an ignored directory is ignored.
        for name, kind in _entries(dirpath):
            if kind == "dir":
                add_all(os.path.join(dirpath, name), rel + name + "/")
            else:
                result.append(rel + name)

    def walk(dirpath, rel, patterns):
        patterns = patterns + _read_gitignore(os.path.join(dirpath, ".gitignore"),
                                              os.fsencode(rel))
        for name, kind in _entries(dirpath):
            path = rel + name
            is_dir = kind == "dir"
            excluded = _is_excluded(os.fsencode(path), is_dir, patterns)
            if is_dir:
                sub = os.path.join(dirpath, name)
                if excluded:
                    add_all(sub, path + "/")
                else:
                    walk(sub, path + "/", patterns)
            elif excluded:
                result.append(path)

    walk(root, "", [])
    return sorted(result)
