"""Decide which files in a project tree are excluded by its .packignore files."""

import os
import re


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    results = []
    _walk(root, root, [], results)
    results.sort()
    return results


def _walk(root, dirpath, inherited, results):
    rel_dir = _relpath(dirpath, root)
    scope_depth = 0 if rel_dir == "" else rel_dir.count("/") + 1

    rules = inherited
    dir_excluded = rel_dir != "" and _excluded(rel_dir.split("/"), True, inherited)
    pack = os.path.join(dirpath, ".packignore")
    if not dir_excluded and os.path.isfile(pack):
        with open(pack, newline="") as f:
            patterns = _parse(f.read())
        if patterns:
            rules = inherited + [(scope_depth, patterns)]

    try:
        entries = os.listdir(dirpath)
    except (FileNotFoundError, PermissionError):
        return
    for name in entries:
        full = os.path.join(dirpath, name)
        if dirpath == root and name == ".git" and os.path.isdir(full):
            continue
        rel = (rel_dir + "/" + name) if rel_dir else name
        if os.path.isdir(full):
            _walk(root, full, rules, results)
        elif os.path.isfile(full):
            parts = rel.split("/")
            if _excluded(parts, False, rules):
                results.append(rel)


def _relpath(dirpath, root):
    r = os.path.relpath(dirpath, root).replace(os.sep, "/")
    return "" if r == "." else r


def _parse(text):
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
            if not line:
                continue
        dir_only = line.endswith("/")
        if dir_only:
            line = line[:-1]
            if not line:
                continue
        anchored = "/" in line
        if anchored and line.startswith("/"):
            line = line[1:]
            if not line:
                continue
        segments = line.split("/")
        if not anchored:
            segments = ["**"] + segments
        compiled = tuple(_compile_segment(s) for s in segments)
        patterns.append((compiled, negated, dir_only))
    return patterns


def _compile_segment(seg):
    if seg == "**":
        return None
    out = []
    for c in seg:
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
    return re.compile("".join(out) + r"\Z", re.DOTALL)


def _excluded(parts, is_dir_target, rules):
    n = len(parts)
    verdicts = [None] * (n + 1)
    for scope_depth, patterns in rules:
        if scope_depth > n:
            continue
        if scope_depth == n and not is_dir_target:
            continue
        for segments, negated, dir_only in patterns:
            for level in range(scope_depth + 1, n + 1):
                is_file_level = (level == n) and not is_dir_target
                if dir_only and is_file_level:
                    continue
                if _match_segs(segments, parts, scope_depth, level):
                    verdicts[level] = not negated
    for level in range(n, 0, -1):
        if verdicts[level] is not None:
            return verdicts[level]
    return False


def _match_segs(segments, parts, start, end):
    path_len = end - start

    def helper(pi, si):
        if pi == len(segments):
            return si == path_len
        seg = segments[pi]
        if seg is None:
            for consume in range(path_len - si + 1):
                if helper(pi + 1, si + consume):
                    return True
            return False
        if si == path_len:
            return False
        if seg.match(parts[start + si]):
            return helper(pi + 1, si + 1)
        return False

    return helper(0, 0)
