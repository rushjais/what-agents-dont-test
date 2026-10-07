"""Decide which files in a project tree are excluded by its .packignore files."""

import os
import re


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    patterns_by_dir = {}
    files = []
    seen = set()
    # canonical: lowered-parent-rel-path -> {lowered_child: canonical_child}.
    # Each path segment is normalized to the first case seen at its level, so
    # case-colliding files/dirs collapse into one canonical entry.
    canonical = {}

    def canon(parts):
        out = []
        key = ""
        for p in parts:
            lo = p.lower()
            m = canonical.setdefault(key, {})
            if lo in m:
                out.append(m[lo])
            else:
                m[lo] = p
                out.append(p)
            key = key + "/" + lo if key else lo
        return out

    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        dir_parts = [] if rel == "." else rel.split("/")
        canon(dir_parts)
        for name in filenames:
            cparts = canon(dir_parts + [name])
            cpath = "/".join(cparts)
            if cpath in seen:
                continue
            seen.add(cpath)
            files.append(cpath)
            if name == ".packignore":
                full = os.path.join(dirpath, name)
                with open(full, newline="") as f:
                    patterns_by_dir["/".join(cparts[:-1])] = _parse(f.read())

    excluded = [fp for fp in files if _is_ignored(fp, patterns_by_dir)]
    return sorted(excluded)


def _parse(text):
    """Parse .packignore content into a list of (is_wild, negated, dir_only, regex)."""
    patterns = []
    for raw in re.split(r"\r\n|\r|\n", text):
        line = raw.strip(" \t")
        if not line or line[0] == ";":
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
        if line.startswith("/"):
            line = line[1:]
            if not line:
                continue
        is_wild = "*" in line or "?" in line
        inner = _glob_to_regex(line)
        full = "^" + inner + "$" if anchored else "^(?:.*/)?" + inner + "$"
        patterns.append((is_wild, negated, dir_only, re.compile(full, re.DOTALL)))
    return patterns


def _glob_to_regex(pat):
    """Translate a glob pattern (no leading /, no trailing /) to a regex pattern string."""
    parts = pat.split("/")
    out = []
    skip_sep = False
    for i, part in enumerate(parts):
        if i > 0:
            if not skip_sep:
                out.append("/")
            skip_sep = False
        if part == "**":
            is_first = i == 0
            is_last = i == len(parts) - 1
            if is_first and is_last:
                out.append(".*")
            elif is_first:
                out.append("(?:.*/)?")
                skip_sep = True
            elif is_last:
                if out and out[-1] == "/":
                    out.pop()
                out.append("(?:/.*)?")
            else:
                out.append("(?:.*/)?")
                skip_sep = True
        else:
            buf = []
            for c in part:
                if c == "*":
                    buf.append("[^/]*")
                elif c == "?":
                    buf.append("[^/]")
                else:
                    buf.append(re.escape(c))
            out.append("".join(buf))
    return "".join(out)


def _is_ignored(file_rel, patterns_by_dir):
    """Decide whether file_rel is excluded.

    Walks packignores from root downward. Within one packignore, patterns are
    applied in order with last-match-wins semantics; a later `!` can re-include
    a file whose ancestor directory an earlier pattern excluded. Across
    packignores, however, if an outer packignore's final verdict excludes the
    file via a match on one of its ancestor directories, an inner packignore
    cannot re-include it.
    """
    parts = file_rel.split("/")
    excluded = False
    sticky = False
    for depth in range(len(parts)):
        pack_dir = "/".join(parts[:depth])
        patterns = patterns_by_dir.get(pack_dir)
        if not patterns:
            continue
        status, via_dir = _packignore_verdict(patterns, parts[depth:])
        if status is None:
            continue
        if sticky:
            continue
        if status:
            excluded = True
            if via_dir:
                sticky = True
        else:
            excluded = False
    return excluded


def _packignore_verdict(patterns, parts):
    """Apply patterns to a file path (relative to the packignore's dir).

    `parts` is the file's path split by "/". The file's ancestor directories
    (relative to the packignore's dir) are parts[:1], parts[:2], ..., parts[:-1];
    the file itself is parts[:len(parts)].

    Within a single .packignore, patterns are partitioned into a literal track
    (no `*` or `?`) and a wildcard track; each track uses last-match-wins. If
    the literal track matched at all, its verdict wins — otherwise the wildcard
    track's does. This makes a literal `!pattern` shield a file from later
    wildcarded exclusions in the same file.

    Returns (status, via_dir): status is None (no match in either track), True
    (excluded by last match), or False (re-included by last match). via_dir is
    True iff the winning match hit an ancestor directory.
    """
    candidates = []
    for k in range(1, len(parts) + 1):
        candidates.append(("/".join(parts[:k]), k < len(parts)))
    lit_status = None
    lit_via = False
    wild_status = None
    wild_via = False
    for is_wild, negated, dir_only, regex in patterns:
        matched_as_dir = False
        matched_as_file = False
        for path, is_dir in candidates:
            if dir_only and not is_dir:
                continue
            if regex.match(path):
                if is_dir:
                    matched_as_dir = True
                else:
                    matched_as_file = True
        if not (matched_as_dir or matched_as_file):
            continue
        if negated:
            new_status = False
            new_via = False
        else:
            new_status = True
            new_via = matched_as_dir
        if is_wild:
            wild_status = new_status
            wild_via = new_via
        else:
            lit_status = new_status
            lit_via = new_via
    if lit_status is not None:
        return lit_status, lit_via
    return wild_status, wild_via
