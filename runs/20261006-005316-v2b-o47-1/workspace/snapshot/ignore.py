"""Decide which files in a project tree are excluded by its .packignore files.

Pure-Python replacement for the legacy ``packignore`` engine. The syntax is a
restricted gitignore dialect (see docs/PACKIGNORE.md), with these notable
differences from gitignore:

- No character classes (``[...]``) or escapes (``\\``); those characters are
  literal.
- Within a single ``.packignore``, a matching negation always re-includes a
  file, regardless of pattern order (not "last match wins").
- Across ``.packignore`` files, the deepest ``.packignore`` with an opinion
  about a file wins. A ``.packignore`` whose own file is excluded by an
  ancestor ``.packignore`` contributes no rules.
"""

import os
import re


def ignored_files(root):
    """Return the files under ``root`` that its .packignore files exclude.

    Paths are relative to ``root``, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A ``.git`` directory directly
    under ``root`` is skipped.
    """
    all_files, packignores = _walk(root)
    live = _live_packignores(packignores)
    return sorted(f for f in all_files if _file_excluded(f, live))


def _walk(root):
    all_files = []
    packignores = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            all_files.append(rel)
            if name == ".packignore":
                with open(os.path.join(dirpath, name), newline="") as f:
                    packignores[rel_dir] = f.read()
    return all_files, packignores


def _live_packignores(packignores):
    """Return {dir: parsed_rules} for .packignores whose directory is not
    excluded by rules from live ancestor .packignores."""
    live = {}
    for d in sorted(packignores, key=lambda s: (s.count("/") if s else -1, s)):
        if d != "" and _path_excluded(d, True, live):
            continue
        live[d] = _parse(packignores[d])
    return live


def _file_excluded(path, live):
    return _path_excluded(path, False, live)


def _path_excluded(path, is_dir, live):
    """Does any live .packignore mark ``path`` as excluded?

    If is_dir, the final path segment is treated as a directory (so dir-only
    rules can match it). Walks live .packignores from shallowest to deepest;
    within one .packignore a matching negation always wins over a matching
    positive, and across .packignores the deepest with an opinion wins.
    """
    f_segs = path.split("/")
    applicable = []
    for d in live:
        if d == "":
            applicable.append(d)
        else:
            d_segs = d.split("/")
            if len(d_segs) < len(f_segs) and f_segs[: len(d_segs)] == d_segs:
                applicable.append(d)
    applicable.sort(key=lambda s: (s.count("/") + 1) if s else 0)

    verdict = False
    for d in applicable:
        depth = 0 if d == "" else d.count("/") + 1
        rel_segs = f_segs[depth:]
        pack_verdict = _packignore_verdict(live[d], rel_segs, is_dir)
        if pack_verdict is not None:
            verdict = pack_verdict
    return verdict


def _packignore_verdict(rules, rel_segs, target_is_dir):
    has_positive = False
    for rule in rules:
        if _rule_matches(rule, rel_segs, target_is_dir):
            if rule["neg"]:
                return False
            has_positive = True
    return True if has_positive else None


def _rule_matches(rule, rel_segs, target_is_dir):
    """Does ``rule`` match the path (file or dir) whose relative segments are
    rel_segs? Matches if the pattern matches the path itself or any prefix
    (ancestor directory). Dir-only rules match only directory paths."""
    n = len(rel_segs)
    for k in range(1, n + 1):
        is_dir_here = (k < n) or target_is_dir
        if rule["dir_only"] and not is_dir_here:
            continue
        prefix = rel_segs[:k]
        if rule["anchored"]:
            if _match_segments(rule["segments"], prefix):
                return True
        else:
            if _segment_match(rule["segments"][0], prefix[-1]):
                return True
    return False


def _match_segments(pat_segs, path_segs, i=0, j=0):
    """Match a list of segment patterns against path segments.

    A segment pattern that is exactly ``**`` matches zero or more path
    segments; any other segment pattern matches exactly one.
    """
    if i == len(pat_segs):
        return j == len(path_segs)
    seg = pat_segs[i]
    if seg == "**":
        for k in range(j, len(path_segs) + 1):
            if _match_segments(pat_segs, path_segs, i + 1, k):
                return True
        return False
    if j == len(path_segs):
        return False
    if _segment_match(seg, path_segs[j]):
        return _match_segments(pat_segs, path_segs, i + 1, j + 1)
    return False


_SEGMENT_RE_CACHE = {}


def _segment_match(seg_pat, seg):
    """Match a single segment pattern against a single path segment."""
    rx = _SEGMENT_RE_CACHE.get(seg_pat)
    if rx is None:
        parts = []
        i = 0
        while i < len(seg_pat):
            c = seg_pat[i]
            if c == "*":
                while i < len(seg_pat) and seg_pat[i] == "*":
                    i += 1
                parts.append(".*")
            elif c == "?":
                parts.append(".")
                i += 1
            else:
                parts.append(re.escape(c))
                i += 1
        rx = re.compile("".join(parts), re.DOTALL)
        _SEGMENT_RE_CACHE[seg_pat] = rx
    return rx.fullmatch(seg) is not None


def _parse(content):
    """Parse .packignore content into a list of rule dicts."""
    rules = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        if neg:
            line = line[1:]
        dir_only = False
        while line.endswith("/"):
            dir_only = True
            line = line[:-1]
        anchored = False
        while line.startswith("/"):
            anchored = True
            line = line[1:]
        if not line:
            continue
        if "/" in line:
            anchored = True
        segments = line.split("/")
        if any(s == "" for s in segments):
            continue
        rules.append({
            "neg": neg,
            "dir_only": dir_only,
            "anchored": anchored,
            "segments": segments,
        })
    return rules
