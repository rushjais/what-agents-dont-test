"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes the original 1.4 behaviour; the engine
had drifted from it, and the rules below follow what the engine actually did.

Syntax of a .packignore file (UTF-8, split with str.splitlines()):

- Each line is stripped of surrounding whitespace (str.strip()). Empty lines
  and lines starting with ";" are ignored. "#" does NOT start a comment.
- A leading "!" (only one) negates the pattern.
- Trailing "/"s are removed and make the pattern match directories only.
- If what remains contains a "/", the pattern is anchored to the directory
  holding the .packignore; leading "/"s are then removed. Otherwise it
  matches a name at any depth.
- "*" (any run of them) matches any characters except "/", "?" matches one
  character except "/". A whole "**" segment matches zero to three path
  segments (not any number); elsewhere "**" acts like "*". Everything else, including "[", "]" and
  "\\", is literal. Matching is case-sensitive.

Evaluation:

- Every regular file under the root is considered (symlinks are not), except
  those in a `.git` directory directly under the root.
- A .packignore applies to everything below its directory, matching against
  paths relative to that directory.
- For a file, the file itself is tested first, then each enclosing directory
  from the innermost outwards. At the first path some rule matches, one rule
  decides: the one from the deepest .packignore, then the most specific one
  (most characters other than "*", "?" and "/"), then the last one in the
  file. It excludes the file, or keeps it if it is a negation. A file that
  nothing matches is kept.
- A .packignore inside a directory that is excluded (by the same procedure)
  is not read. Being matched itself does not stop a .packignore being read.
"""

import os
import re

_NAME = ".packignore"
_MAX_DOUBLE_STAR = 3  # a "**" segment spans at most this many path segments


def _compile(pattern):
    """Translate a cleaned-up pattern into a regex.

    The regex is matched against a relative path with a "/" appended, so every
    segment, including the last, is followed by a "/".
    """
    out = []
    for seg in pattern.split("/"):
        if seg == "**":
            out.append("(?:[^/]*/){0,%d}" % _MAX_DOUBLE_STAR)
            continue
        for tok in re.findall(r"\*+|\?|[^*?]+", seg):
            if tok[0] == "*":
                out.append("[^/]*")
            elif tok == "?":
                out.append("[^/]")
            else:
                out.append(re.escape(tok))
        out.append("/")
    return "".join(out)


def _parse(text):
    """Return the rules in a .packignore file as (negate, dir_only, score, regex)."""
    rules = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        negate = s.startswith("!")
        if negate:
            s = s[1:]
        dir_only = s.endswith("/")
        s = s.rstrip("/")
        anchored = "/" in s
        s = s.lstrip("/")
        if not s:
            continue
        regex = _compile(s)
        if not anchored:
            regex = "(?:[^/]*/)*" + regex
        score = sum(c not in "*?/" for c in s)
        rules.append((negate, dir_only, score, re.compile(regex, re.DOTALL)))
    return rules


def _files(root):
    """Yield every regular file under `root` as a "/"-separated relative path."""
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            yield os.path.relpath(full, root).replace(os.sep, "/")


def _dirs_of(path):
    """Return the enclosing directories of `path`, outermost first ("" is the root)."""
    parts = path.split("/")[:-1]
    return [""] + ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    files = sorted(_files(root))
    present = set(files)
    dirs = sorted({d for f in files for d in _dirs_of(f)}, key=lambda d: (d.count("/"), d))
    excluded = {"": False}  # directory -> whether it is excluded
    rules = {}  # directory -> rules from its .packignore, if that is read

    def decide(path, is_dir):
        """Return True/False if a rule matches `path` itself, else None."""
        best = None
        for depth, d in enumerate(_dirs_of(path)):
            rel = path[len(d) + 1:] if d else path
            for index, (negate, dir_only, score, regex) in enumerate(rules[d]):
                if dir_only and not is_dir:
                    continue
                if regex.fullmatch(rel + "/"):
                    key = (depth, score, index)
                    if best is None or key > best[0]:
                        best = (key, not negate)
        return None if best is None else best[1]

    def is_excluded(path, is_dir):
        verdict = decide(path, is_dir)
        return excluded[path.rpartition("/")[0]] if verdict is None else verdict

    # Parents come before their children, so everything a directory's verdict
    # depends on is known by the time it is reached.
    for d in dirs:
        if d:
            excluded[d] = is_excluded(d, True)
        ignore_file = (d + "/" if d else "") + _NAME
        rules[d] = []
        if ignore_file in present and not excluded[d]:
            with open(os.path.join(root, *ignore_file.split("/")), encoding="utf-8") as f:
                rules[d] = _parse(f.read())

    return [f for f in files if is_excluded(f, False)]
