"""Decide which files in a project tree are ignored by its .gitignore files.

This is a pure-Python port of the parts of git (v2.47) that answer
`git ls-files --others --ignored --exclude-standard` in a fresh repository
with `core.ignorecase=false` and no global or repository-level excludes:
the directory walk and exclude stack from dir.c, and the glob matcher from
wildmatch.c. The structure deliberately mirrors git's code, including its
quirks, so that results are identical; refer to those files when changing it.

All matching is done on bytes, exactly as git does.
"""

import os

# --- character classes (git's sane-ctype.h / ctype.c) -----------------------

_SPACE, _DIGIT, _ALPHA, _GLOB, _REGEX, _MAGIC, _CNTRL, _PUNCT = (
    0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)


def _build_ctype():
    S, A, D, G, R, P, X, U = _SPACE, _ALPHA, _DIGIT, _GLOB, _REGEX, _MAGIC, _CNTRL, _PUNCT
    Z = _CNTRL | _SPACE
    table = [
        X, X, X, X, X, X, X, X, X, Z, Z, X, X, Z, X, X,
        X, X, X, X, X, X, X, X, X, X, X, X, X, X, X, X,
        S, P, P, P, R, P, P, P, R, R, G, R, P, P, R, P,
        D, D, D, D, D, D, D, D, D, D, P, P, P, P, P, G,
        P, A, A, A, A, A, A, A, A, A, A, A, A, A, A, A,
        A, A, A, A, A, A, A, A, A, A, A, G, G, U, R, P,
        P, A, A, A, A, A, A, A, A, A, A, A, A, A, A, A,
        A, A, A, A, A, A, A, A, A, A, A, R, R, U, P, X,
    ]
    return table + [0] * 128


_CTYPE = _build_ctype()


def _test(c, mask):
    return (_CTYPE[c] & mask) != 0


def _is_glob_special(c):
    return _test(c, _GLOB)


def _islower(c):
    return _test(c, _ALPHA) and (c & 0x20) != 0


def _isupper(c):
    return _test(c, _ALPHA) and (c & 0x20) == 0


# Character classes for "[[:name:]]"; only ASCII ever matches.
_CLASSES = {
    b"alnum": lambda c: _test(c, _ALPHA | _DIGIT),
    b"alpha": lambda c: _test(c, _ALPHA),
    b"blank": lambda c: c in (0x20, 0x09),
    b"cntrl": lambda c: _test(c, _CNTRL),
    b"digit": lambda c: _test(c, _DIGIT),
    b"graph": lambda c: 0x21 <= c <= 0x7e,
    b"lower": _islower,
    b"print": lambda c: 0x20 <= c <= 0x7e,
    b"punct": lambda c: _test(c, _PUNCT | _REGEX | _GLOB | _MAGIC),
    b"space": lambda c: _test(c, _SPACE),
    b"upper": _isupper,
    b"xdigit": lambda c: c in b"0123456789abcdefABCDEF",
}

# --- wildmatch.c -------------------------------------------------------------

_MATCH, _NOMATCH, _ABORT_ALL, _ABORT_TO_STARSTAR = 0, 1, -1, -2

_STAR, _QMARK, _LBRACKET, _RBRACKET, _BACKSLASH, _SLASH = b"*?[]\\/"
_BANG, _CARET, _DASH, _COLON = b"!^-:"


def _dowild(p, pi, t, ti, pathname):
    """Match p[pi:] against t[ti:]. Both are NUL-terminated byte strings."""
    pattern = pi
    while True:
        p_ch = p[pi]
        if p_ch == 0:
            break
        t_ch = t[ti]
        if t_ch == 0 and p_ch != _STAR:
            return _ABORT_ALL
        if p_ch == _BACKSLASH:
            # Literal match with following character.
            pi += 1
            if t_ch != p[pi]:
                return _NOMATCH
        elif p_ch == _QMARK:
            if pathname and t_ch == _SLASH:
                return _NOMATCH
        elif p_ch == _STAR:
            pi += 1
            if p[pi] == _STAR:
                prev_p = pi
                pi += 1
                while p[pi] == _STAR:
                    pi += 1
                if not pathname:
                    match_slash = True
                elif ((prev_p - pattern < 2 or p[prev_p - 2] == _SLASH) and
                      (p[pi] == 0 or p[pi] == _SLASH or
                       (p[pi] == _BACKSLASH and p[pi + 1] == _SLASH))):
                    if (p[pi] == _SLASH and
                            _dowild(p, pi + 1, t, ti, pathname) == _MATCH):
                        return _MATCH
                    match_slash = True
                else:
                    match_slash = False
            else:
                match_slash = not pathname
            if p[pi] == 0:
                # Trailing "**" matches everything; trailing "*" only if
                # there are no more slashes.
                if not match_slash and t.find(b"/", ti) >= 0:
                    return _ABORT_TO_STARSTAR
                return _MATCH
            elif not match_slash and p[pi] == _SLASH:
                # One asterisk followed by a slash matches the next directory.
                slash = t.find(b"/", ti)
                if slash < 0:
                    return _ABORT_ALL
                ti = slash + 1  # the slash is consumed here
                pi += 1
                continue
            while True:
                if t_ch == 0:
                    break
                # Advance quickly to the literal that follows the asterisk.
                if not _is_glob_special(p[pi]):
                    p_ch = p[pi]
                    while True:
                        t_ch = t[ti]
                        if t_ch == 0 or (not match_slash and t_ch == _SLASH):
                            break
                        if t_ch == p_ch:
                            break
                        ti += 1
                    if t_ch != p_ch:
                        return _ABORT_ALL if match_slash else _ABORT_TO_STARSTAR
                matched = _dowild(p, pi, t, ti, pathname)
                if matched != _NOMATCH:
                    if not match_slash or matched != _ABORT_TO_STARSTAR:
                        return matched
                elif not match_slash and t_ch == _SLASH:
                    return _ABORT_TO_STARSTAR
                ti += 1
                t_ch = t[ti]
            return _ABORT_ALL
        elif p_ch == _LBRACKET:
            pi += 1
            p_ch = p[pi]
            if p_ch == _CARET:
                p_ch = _BANG
            negated = p_ch == _BANG
            if negated:
                pi += 1
                p_ch = p[pi]
            prev_ch = 0
            matched = False
            while True:
                if not p_ch:
                    return _ABORT_ALL
                if p_ch == _BACKSLASH:
                    pi += 1
                    p_ch = p[pi]
                    if not p_ch:
                        return _ABORT_ALL
                    if t_ch == p_ch:
                        matched = True
                elif (p_ch == _DASH and prev_ch and p[pi + 1] and
                      p[pi + 1] != _RBRACKET):
                    pi += 1
                    p_ch = p[pi]
                    if p_ch == _BACKSLASH:
                        pi += 1
                        p_ch = p[pi]
                        if not p_ch:
                            return _ABORT_ALL
                    if prev_ch <= t_ch <= p_ch:
                        matched = True
                    p_ch = 0  # makes prev_ch 0
                elif p_ch == _LBRACKET and p[pi + 1] == _COLON:
                    pi += 2
                    s = pi
                    while p[pi] and p[pi] != _RBRACKET:
                        pi += 1
                    p_ch = p[pi]
                    if not p_ch:
                        return _ABORT_ALL
                    i = pi - s - 1
                    if i < 0 or p[pi - 1] != _COLON:
                        # Didn't find ":]", so treat like a normal set.
                        pi = s - 2
                        p_ch = _LBRACKET
                        if t_ch == p_ch:
                            matched = True
                    else:
                        test = _CLASSES.get(p[s:s + i])
                        if test is None:  # malformed [:class:]
                            return _ABORT_ALL
                        if test(t_ch):
                            matched = True
                        p_ch = 0  # makes prev_ch 0
                elif t_ch == p_ch:
                    matched = True
                prev_ch = p_ch
                pi += 1
                p_ch = p[pi]
                if p_ch == _RBRACKET:
                    break
            if matched == negated or (pathname and t_ch == _SLASH):
                return _NOMATCH
        else:
            if t_ch != p_ch:
                return _NOMATCH
        pi += 1
        ti += 1
    return _NOMATCH if t[ti] else _MATCH


def _wildmatch(pattern, text, pathname):
    return _dowild(pattern + b"\0", 0, text + b"\0", 0, pathname) == _MATCH


# --- patterns (dir.c) --------------------------------------------------------

_NEGATIVE, _MUSTBEDIR, _NODIR, _ENDSWITH = 1, 2, 4, 8


def _simple_length(s):
    for i, c in enumerate(s):
        if _is_glob_special(c):
            return i
    return len(s)


class _Pattern:
    __slots__ = ("pattern", "nowildcardlen", "flags", "base")

    def __init__(self, line, base):
        flags = 0
        if line[:1] == b"!":
            flags |= _NEGATIVE
            line = line[1:]
        if line.endswith(b"/"):
            flags |= _MUSTBEDIR
            line = line[:-1]
        if b"/" not in line:
            flags |= _NODIR
        if line[:1] == b"*" and _simple_length(line[1:]) == len(line) - 1:
            flags |= _ENDSWITH
        self.pattern = line
        self.nowildcardlen = _simple_length(line)
        self.flags = flags
        self.base = base  # directory of the .gitignore, without trailing "/"


def _trim_trailing_spaces(s):
    last_space = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == 0x20:
            if last_space is None:
                last_space = i
        elif c == 0x5C:
            i += 1
            if i >= n:
                return s
            last_space = None
        else:
            last_space = None
        i += 1
    return s if last_space is None else s[:last_space]


def _parse_patterns(buf, base):
    if buf.startswith(b"\xef\xbb\xbf"):
        buf = buf[3:]
    patterns = []
    lines = buf.split(b"\n")
    lines.pop()  # buf always ends with "\n"; the last piece is not a line
    for line in lines:
        if not line or line[:1] == b"#":
            continue
        if line.endswith(b"\r"):
            line = line[:-1]
        line = line.split(b"\0", 1)[0]
        patterns.append(_Pattern(_trim_trailing_spaces(line), base))
    return patterns


_PATTERN_MAX_FILE_SIZE = 100 * 1024 * 1024


def _read_gitignore(path, base):
    """Read the patterns of one .gitignore; symlinks are not followed."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return []
    try:
        size = os.fstat(fd).st_size
        if size == 0:
            return []
        chunks, remaining = [], size
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                return []
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        return []
    finally:
        os.close(fd)
    buf = b"".join(chunks) + b"\n"
    if len(buf) > _PATTERN_MAX_FILE_SIZE:
        return []
    return _parse_patterns(buf, base)


def _match_basename(basename, pattern, prefix, flags):
    if prefix == len(pattern):
        return pattern == basename
    if flags & _ENDSWITH:
        return basename.endswith(pattern[1:])
    return _wildmatch(pattern, basename, False)


def _match_pathname(pathname, base, pattern, prefix):
    if pattern[:1] == b"/":
        pattern = pattern[1:]
        prefix -= 1
    baselen = len(base)
    if (len(pathname) < baselen + 1 or
            (baselen and pathname[baselen] != _SLASH) or
            pathname[:baselen] != base):
        return False
    name = pathname[baselen + 1:] if baselen else pathname
    if prefix:
        if prefix > len(name):
            return False
        if pattern[:prefix] != name[:prefix]:
            return False
        pattern = pattern[prefix:]
        name = name[prefix:]
        if not pattern and not name:
            return True
    return _wildmatch(pattern, name, True)


def _last_matching_pattern(lists, pathname, is_dir):
    """Find the pattern that decides `pathname`, or None.

    `lists` holds one pattern list per .gitignore, outermost first; deeper
    files take precedence, and within a file the last matching line wins.
    """
    basename = pathname[pathname.rfind(b"/") + 1:]
    for patterns in reversed(lists):
        for pat in reversed(patterns):
            if pat.flags & _MUSTBEDIR and not is_dir:
                continue
            if pat.flags & _NODIR:
                if _match_basename(basename, pat.pattern, pat.nowildcardlen,
                                   pat.flags):
                    return pat
            elif _match_pathname(pathname, pat.base, pat.pattern,
                                 pat.nowildcardlen):
                return pat
    return None


def _is_excluded(lists, pathname, is_dir):
    pat = _last_matching_pattern(lists, pathname, is_dir)
    return pat is not None and not pat.flags & _NEGATIVE


# --- nested repositories (setup.c) -------------------------------------------

def _validate_headref(path):
    try:
        if os.path.islink(path):
            return os.readlink(path)[:5] == b"refs/"
        with open(path, "rb") as f:
            buf = f.read(255)
    except OSError:
        return False
    buf = buf.split(b"\0", 1)[0]
    if buf.startswith(b"ref:"):
        ref = buf[4:].lstrip(b" \t\n\r")
        if ref.startswith(b"refs/"):
            return True
    hexdigits = b"0123456789abcdefABCDEF"
    for n in (64, 40):
        if len(buf) >= n and all(c in hexdigits for c in buf[:n]):
            return True
    return False


def _is_git_directory(suspect):
    if not _validate_headref(os.path.join(suspect, b"HEAD")):
        return False
    common = suspect
    commondir = os.path.join(suspect, b"commondir")
    if os.path.exists(commondir):
        try:
            with open(commondir, "rb") as f:
                data = f.read().rstrip(b"\r\n")
        except OSError:
            return False
        common = data if os.path.isabs(data) else suspect + b"/" + data
    return (os.access(os.path.join(common, b"objects"), os.X_OK) and
            os.access(os.path.join(common, b"refs"), os.X_OK))


def _is_nested_repo(dirpath):
    gitpath = os.path.join(dirpath, b".git")
    try:
        st = os.stat(gitpath)
    except OSError:
        return _is_git_directory(gitpath)
    if os.path.stat.S_ISREG(st.st_mode) and st.st_size <= 1 << 20:
        try:
            with open(gitpath, "rb") as f:
                buf = f.read()
        except OSError:
            return True  # git treats unreadable gitfiles as repositories
        if len(buf) != st.st_size:
            return True
        if buf.startswith(b"gitdir: "):
            while buf.endswith((b"\n", b"\r")):
                buf = buf[:-1]
            if len(buf) >= 9:
                gitdir = buf[8:].split(b"\0", 1)[0]
                if not os.path.isabs(gitdir):
                    gitdir = dirpath + b"/" + gitdir
                if _is_git_directory(gitdir):
                    return True
    return _is_git_directory(gitpath)


# --- directory walk ----------------------------------------------------------

def _walk(top, rel, lists, excluded_dir, out):
    """Collect ignored entries below `top` (whose path relative to the root
    is `rel`, b"" for the root itself).

    `lists` are the .gitignore pattern lists in effect; `excluded_dir` is true
    when an enclosing directory is ignored, which ignores everything below.
    """
    try:
        entries = list(os.scandir(top))
    except OSError:
        return
    for entry in entries:
        name = entry.name
        if name == b".git":
            continue
        path = rel + b"/" + name if rel else name
        try:
            if entry.is_symlink():
                is_dir = False
            elif entry.is_dir(follow_symlinks=False):
                is_dir = True
            elif entry.is_file(follow_symlinks=False):
                is_dir = False
            else:
                continue  # sockets, fifos, devices: git skips them
        except OSError:
            continue
        excluded = excluded_dir or _is_excluded(lists, path, is_dir)
        if not is_dir:
            if excluded:
                out.append(path)
            continue
        if _is_nested_repo(entry.path):
            # git lists an ignored nested repository as a single "dir/" entry.
            if excluded:
                out.append(path + b"/")
            continue
        if excluded:
            _walk(entry.path, path, lists, True, out)
        else:
            sub = _read_gitignore(os.path.join(entry.path, b".gitignore"), path)
            _walk(entry.path, path, lists + [sub], False, out)


def ignored_files(root):
    """Return the files under `root` that its .gitignore files ignore.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. Only .gitignore files inside
    `root` are consulted; a `.git` directory directly under `root` is skipped.
    """
    top = os.fsencode(root)
    lists = [_read_gitignore(os.path.join(top, b".gitignore"), b"")]
    out = []
    _walk(top, b"", lists, False, out)
    return sorted(os.fsdecode(p) for p in out)
