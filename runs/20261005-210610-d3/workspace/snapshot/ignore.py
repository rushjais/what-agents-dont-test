"""Decide which files in a project tree are ignored by its .gitignore files.

A pure-Python reimplementation of the subset of git's gitignore matching we
need: only `.gitignore` files inside the tree are consulted (no global
excludes, no `.git/info/exclude`) and matching is case-sensitive. Behaviour
is otherwise meant to match `git ls-files --others --ignored --exclude-standard`
on the same tree.
"""

import os
import re
import stat
from collections import namedtuple

Rule = namedtuple("Rule", ["regex", "negate", "dir_only", "anchored"])


def ignored_files(root):
    """Return the files under `root` that its .gitignore files ignore.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. Only .gitignore files inside
    `root` are consulted; `.git` entries at any depth are skipped.
    """
    result = []
    _walk(root, "", [], result)
    return sorted(result)


def _walk(abs_dir, rel_dir, rule_sets, result):
    gi_path = os.path.join(abs_dir, ".gitignore")
    if os.path.isfile(gi_path):
        local = _load_gitignore(gi_path)
        if local:
            rule_sets = rule_sets + [(rel_dir, local)]

    try:
        entries = os.listdir(abs_dir)
    except OSError:
        return

    for name in entries:
        if name == ".git":
            continue
        entry_abs = os.path.join(abs_dir, name)
        entry_rel = f"{rel_dir}/{name}" if rel_dir else name

        try:
            st = os.lstat(entry_abs)
        except OSError:
            continue

        if stat.S_ISLNK(st.st_mode):
            is_dir = False
        elif stat.S_ISDIR(st.st_mode):
            is_dir = True
        else:
            is_dir = False

        if _is_ignored(rule_sets, entry_rel, is_dir):
            if is_dir:
                _list_all_files(entry_abs, entry_rel, result)
            else:
                result.append(entry_rel)
        elif is_dir:
            _walk(entry_abs, entry_rel, rule_sets, result)


def _list_all_files(abs_dir, rel_dir, result):
    """List every file under abs_dir (treating symlinks as files)."""
    try:
        entries = os.listdir(abs_dir)
    except OSError:
        return
    for name in entries:
        if name == ".git":
            continue
        entry_abs = os.path.join(abs_dir, name)
        entry_rel = f"{rel_dir}/{name}"
        try:
            st = os.lstat(entry_abs)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode):
            result.append(entry_rel)
        elif stat.S_ISDIR(st.st_mode):
            _list_all_files(entry_abs, entry_rel, result)
        else:
            result.append(entry_rel)


def _is_ignored(rule_sets, path, is_dir):
    """Apply rule_sets (ordered shallowest-first) to `path`; last match wins.

    Anchored rules (any `/` in the pattern beyond the trailing one) match the
    full path relative to the `.gitignore`'s directory; unanchored rules match
    the basename of the current entry only.
    """
    ignored = False
    basename = path.rsplit("/", 1)[-1]
    for source_dir, rules in rule_sets:
        if source_dir:
            subpath = path[len(source_dir) + 1:]
        else:
            subpath = path
        for rule in rules:
            if rule.dir_only and not is_dir:
                continue
            target = subpath if rule.anchored else basename
            if rule.regex.match(target):
                ignored = not rule.negate
    return ignored


def _load_gitignore(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="surrogateescape")
    rules = []
    for line in text.split("\n"):
        rule = _parse_line(line)
        if rule is not None:
            rules.append(rule)
    return rules


_TRAILING_WS = " \t\r\v\f"


def _parse_line(line):
    if not line or line[0] == "#":
        return None

    line = _strip_trailing(line)
    if not line:
        return None

    negate = False
    if line[0] == "!":
        negate = True
        line = line[1:]
    if not line:
        return None

    dir_only = False
    if line.endswith("/"):
        dir_only = True
        line = line[:-1]
    if not line:
        return None

    if "/" in line:
        anchored = True
        if line.startswith("/"):
            line = line[1:]
    else:
        anchored = False
    if not line:
        return None

    body = _translate_glob(line)
    if body is None:
        return None
    regex = re.compile(body + r"\Z")
    return Rule(regex=regex, negate=negate, dir_only=dir_only, anchored=anchored)


def _strip_trailing(line):
    """Strip trailing whitespace, respecting `\\` escapes.

    Mirrors git's trim_trailing_spaces: walks the string tracking the start of
    the final unescaped whitespace run and truncates there. Returns None if the
    line ends with an unterminated backslash escape (git skips those lines).
    """
    last_space = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c in _TRAILING_WS:
            if last_space is None:
                last_space = i
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                return None
            i += 2
            last_space = None
        else:
            last_space = None
            i += 1
    if last_space is not None:
        return line[:last_space]
    return line


def _translate_glob(pat):
    """Translate a gitignore glob body to a regex body.

    `pat` has leading `!`, leading/trailing `/`, and any already-stripped
    whitespace removed; it never ends with an unescaped `/`. Returns None if
    the pattern is malformed (e.g. unterminated `[`), matching git's behaviour
    of rejecting such patterns entirely.
    """
    i = 0
    n = len(pat)
    out = []
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                j = i + 2
                while j < n and pat[j] == "*":
                    j += 1
                # `**` is a path-crossing wildcard whenever it is adjacent to
                # a `/` or the end of the pattern on either side; otherwise
                # the git docs call it "regular asterisks" (equivalent to `*`).
                if j == n:
                    out.append(".*")
                    i = j
                elif pat[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append("[^/]*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                if pat[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j >= n:
                return None  # unterminated [ — git drops the whole pattern
            out.append("[" + _translate_class(pat[i + 1:j]) + "]")
            i = j + 1
        elif c == "\\":
            if i + 1 < n:
                out.append(re.escape(pat[i + 1]))
                i += 2
            else:
                out.append(re.escape("\\"))
                i += 1
        elif c == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _translate_class(content):
    """Translate `[...]` body from glob to regex syntax."""
    out = []
    k = 0
    m = len(content)
    if m > 0 and content[0] == "!":
        out.append("^")
        k = 1
    while k < m:
        c = content[k]
        if c == "\\" and k + 1 < m:
            nx = content[k + 1]
            if nx in r"\]^-":
                out.append("\\" + nx)
            else:
                out.append(nx)
            k += 2
        elif c == "\\":
            out.append("\\\\")
            k += 1
        else:
            out.append(c)
            k += 1
    return "".join(out)
