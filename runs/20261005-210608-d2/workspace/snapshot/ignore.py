"""Decide which files in a project tree are ignored by its .gitignore files.

Pure Python replacement for the previous git-based implementation. Replicates
the behavior of
    git -c core.ignorecase=false -c core.excludesFile=/dev/null \\
        ls-files -z --others --ignored --exclude-standard
on a fresh scratch repository with no index, so only .gitignore files inside
the tree are consulted.
"""

import os
import re


def ignored_files(root):
    """Return the files under `root` that its .gitignore files ignore.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. Only .gitignore files inside
    `root` are consulted; a `.git` entry directly under `root` is skipped.
    """
    result = []
    _walk(root, "", (), result, is_root=True)
    return sorted(result)


def _walk(abs_dir, rel_dir, patterns, result, is_root):
    local_patterns = patterns
    gi_path = os.path.join(abs_dir, ".gitignore")
    if os.path.isfile(gi_path) and not os.path.islink(gi_path):
        new = _load_gitignore(gi_path, rel_dir)
        if new:
            local_patterns = patterns + tuple(new)

    try:
        entries = os.listdir(abs_dir)
    except OSError:
        return

    for name in entries:
        if is_root and name == ".git":
            continue
        abs_path = os.path.join(abs_dir, name)
        rel_path = (rel_dir + "/" + name) if rel_dir else name
        is_dir = os.path.isdir(abs_path) and not os.path.islink(abs_path)

        if is_dir:
            if _is_ignored(rel_path, True, local_patterns):
                _collect_all(abs_path, rel_path, result)
            else:
                _walk(abs_path, rel_path, local_patterns, result, False)
        else:
            if _is_ignored(rel_path, False, local_patterns):
                result.append(rel_path)


def _collect_all(abs_dir, rel_dir, result):
    """Enumerate every file under `abs_dir`, descending into subdirectories."""
    try:
        entries = os.listdir(abs_dir)
    except OSError:
        return
    for name in entries:
        abs_path = os.path.join(abs_dir, name)
        rel_path = rel_dir + "/" + name
        if os.path.isdir(abs_path) and not os.path.islink(abs_path):
            _collect_all(abs_path, rel_path, result)
        else:
            result.append(rel_path)


def _load_gitignore(gi_path, gi_dir):
    patterns = []
    try:
        with open(gi_path, "rb") as f:
            data = f.read()
    except OSError:
        return patterns
    # Strip UTF-8 BOM if present, decode permissively.
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace")
    for raw in text.splitlines():
        parsed = _parse_line(raw)
        if parsed is None:
            continue
        regex, negate, dir_only = parsed
        patterns.append((gi_dir, re.compile(regex), negate, dir_only))
    return patterns


def _is_ignored(rel_path, is_dir, patterns):
    ignored = False
    for gi_dir, regex, negate, dir_only in patterns:
        if gi_dir:
            prefix = gi_dir + "/"
            if not rel_path.startswith(prefix):
                continue
            path_in = rel_path[len(prefix):]
        else:
            path_in = rel_path
        if dir_only and not is_dir:
            continue
        if regex.match(path_in):
            ignored = not negate
    return ignored


def _parse_line(line):
    # Strip a trailing CR (handles CRLF via splitlines + lone CR here).
    if line.endswith("\r"):
        line = line[:-1]

    # Drop trailing unescaped whitespace. A space is escaped iff the number of
    # consecutive preceding backslashes is odd.
    i = len(line)
    while i > 0 and line[i - 1] in " \t":
        bs = 0
        j = i - 2
        while j >= 0 and line[j] == "\\":
            bs += 1
            j -= 1
        if bs % 2 == 1:
            break
        i -= 1
    line = line[:i]

    if not line or line[0] == "#":
        return None

    negate = False
    if line[0] == "!":
        negate = True
        line = line[1:]

    if line.startswith("\\#") or line.startswith("\\!"):
        line = line[1:]

    dir_only = False
    if line.endswith("/"):
        dir_only = True
        line = line[:-1]

    if not line:
        return None

    anchored = "/" in line
    if line.startswith("/"):
        line = line[1:]
    elif line.startswith("**/"):
        anchored = False
        line = line[3:]

    if not line:
        return None

    regex = _glob_to_regex(line, anchored)
    return (regex, negate, dir_only)


def _glob_to_regex(pattern, anchored):
    """Convert a normalized gitignore pattern to a full-match regex string.

    `pattern` has no leading `/`, no trailing `/`, and no leading `**/`. If
    `anchored`, the pattern matches starting at the .gitignore's directory;
    otherwise it may match at any depth below it.
    """
    out = []
    i = 0
    n = len(pattern)

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                prev_slash = (i == 0) or pattern[i - 1] == "/"
                next_i = i + 2
                next_slash = (next_i >= n) or pattern[next_i] == "/"
                if prev_slash and next_slash:
                    # Standalone ** component.
                    if next_i >= n:
                        # Trailing /** or lone ** at start-of-pattern.
                        if out and out[-1] == "/":
                            out.pop()
                            out.append("/.*")
                        else:
                            out.append(".*")
                        i = next_i
                    elif i == 0:
                        # Leading **/ (anchored patterns only; non-anchored
                        # already had leading **/ stripped before we got here).
                        out.append("(?:[^/]+/)*")
                        i = next_i + 1
                    else:
                        # Middle /**/ — zero or more directory components.
                        if out and out[-1] == "/":
                            out.pop()
                        out.append("(?:/[^/]+)*/")
                        i = next_i + 1
                else:
                    # ** not surrounded by slashes: treat as a single *.
                    out.append("[^/]*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            end = _find_class_end(pattern, i)
            if end == -1:
                out.append(re.escape(c))
                i += 1
            else:
                out.append(_translate_class(pattern[i:end + 1]))
                i = end + 1
        elif c == "\\":
            if i + 1 < n:
                out.append(re.escape(pattern[i + 1]))
                i += 2
            else:
                out.append(re.escape(c))
                i += 1
        elif c == "/":
            out.append("/")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1

    body = "".join(out)
    if anchored:
        return r"\A" + body + r"\Z"
    return r"\A(?:[^/]*/)*" + body + r"\Z"


def _find_class_end(pattern, start):
    """Return the index of the closing ']' for a `[...]` class starting at
    `start`, or -1 if the class is unterminated."""
    i = start + 1
    n = len(pattern)
    if i < n and pattern[i] in "!^":
        i += 1
    # A ']' as the first class member is literal.
    if i < n and pattern[i] == "]":
        i += 1
    while i < n:
        if pattern[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if pattern[i] == "/":
            return -1
        if pattern[i] == "]":
            return i
        i += 1
    return -1


def _translate_class(src):
    """Translate `[...]` glob class to a regex class. `src` includes brackets."""
    inner = src[1:-1]
    out = ["["]
    if inner and inner[0] in "!^":
        out.append("^")
        inner = inner[1:]
    i = 0
    n = len(inner)
    while i < n:
        c = inner[i]
        if c == "\\" and i + 1 < n:
            nxt = inner[i + 1]
            if nxt in r"\]^-":
                out.append("\\" + nxt)
            else:
                out.append(re.escape(nxt))
            i += 2
        elif c in r"\]":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    out.append("]")
    return "".join(out)
