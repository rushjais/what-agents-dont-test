"""Decide which files in a project tree are excluded by its .packignore files.

This is a pure-Python reimplementation of `packignore`, the legacy exclusion
engine. docs/PACKIGNORE.md describes it loosely; the rules it actually follows
are:

Reading the tree
  * Regular files only: symlinks are skipped and not followed. A `.git`
    directory directly under the root is skipped.
  * Names are compared the way packignore's storage compares them: ignoring
    case and Unicode normalization. When two paths collide, the name seen
    first is kept and the contents seen last win. A file colliding with a
    directory, or a hard link to a file already seen, is an error.

Reading a .packignore file (UTF-8; only files named exactly `.packignore`)
  * Lines are split as by `str.splitlines` and stripped of whitespace.
    Blank lines and lines starting with `;` are skipped. `#` is not special,
    and neither is `\\`.
  * A leading `!` negates the rule; the rest of the line is the pattern,
    taken as is.
  * Trailing `/`s make the rule match directories only. A pattern still
    containing a `/` after they are removed is anchored to the .packignore's
    directory (leading `/`s are dropped); otherwise it matches a name at any
    depth.
  * `{a,b}` alternatives are expanded (the first `{` pairs with the next
    `}`; groups do not nest). `*` matches within a path segment and `?`
    matches one character of it. A segment that is exactly `**` matches zero
    to three segments; `**` inside a segment acts like `*`. Everything else,
    including `[`, matches literally and case-sensitively.

Deciding
  * A path is decided at its own level first: among the .packignore files
    above it, the deepest one with a matching rule decides. Within that
    file the most specific matching rule wins, where specificity is the
    number of characters in the pattern other than `*?/{},`; ties go to the
    later rule.
  * If no rule matches the path itself, a file that is executable (any of
    the 0o111 mode bits) or whose first line contains `@generated` is
    excluded; anything else inherits the decision for its directory.
  * The .packignore of an excluded directory is not read.
"""

import os
import re
import unicodedata

_IGNORE_FILE = ".packignore"


def ignored_files(root):
    """Return the files under `root` that its .packignore files exclude.

    Paths are relative to `root`, use "/" as the separator, and are sorted.
    Only files are listed, never directories. A `.git` directory directly
    under `root` is skipped.
    """
    tree = _load_tree(root)
    found = []
    _evaluate(tree, [], [], False, found)
    # packignore reported one path per line; reproduce how that output split.
    return sorted(line for line in "\n".join(found).splitlines() if line)


# --- reading the tree ---------------------------------------------------------

class _Dir:
    def __init__(self, name):
        self.name = name
        self.children = {}  # folded name -> _Dir or _File


class _File:
    def __init__(self, name):
        self.name = name
        self.source = None  # filesystem path of the contents
        self.excluded_by_default = False


def _fold(name):
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def _load_tree(root):
    top = _Dir("")
    seen_inodes = set()
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.samefile(dirpath, root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            try:
                rel.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError(f"file name is not valid UTF-8: {rel!r}") from None
            st = os.lstat(full)
            if st.st_nlink > 1:
                inode = (st.st_ino, st.st_dev)
                if inode in seen_inodes:
                    raise ValueError(f"unsupported entry (only regular files and directories): {rel!r}")
                seen_inodes.add(inode)
            node = _add_file(top, rel)
            node.source = full
            node.excluded_by_default = bool(st.st_mode & 0o111) or _is_generated(full)
    return top


def _add_file(top, rel):
    """Return the node for file `rel`, creating it (and its directories) if needed."""
    node = top
    *dirs, base = rel.split("/")
    for part in dirs:
        child = node.children.get(_fold(part))
        if child is None:
            child = node.children[_fold(part)] = _Dir(part)
        elif not isinstance(child, _Dir):
            raise ValueError(f"path conflicts with a file: {rel!r}")
        node = child
    child = node.children.get(_fold(base))
    if child is None:
        child = node.children[_fold(base)] = _File(base)
    elif not isinstance(child, _File):
        raise ValueError(f"path conflicts with a directory: {rel!r}")
    return child


def _is_generated(path):
    """Whether the file's first line (bytes up to the first "\\n") contains "@generated"."""
    marker = b"@generated"
    tail = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                return False
            line, newline, _ = chunk.partition(b"\n")
            if marker in tail + line:
                return True
            if newline:
                return False
            tail = line[-(len(marker) - 1):]


# --- rules --------------------------------------------------------------------

_NOT_LITERAL = frozenset("*?/{},")


class _Rule:
    def __init__(self, negate, dir_only, anchored, specificity, regexes):
        self.negate = negate
        self.dir_only = dir_only
        self.anchored = anchored
        self.specificity = specificity
        self.regexes = regexes

    def matches(self, rel, name, is_dir):
        if self.dir_only and not is_dir:
            return False
        subject = (rel if self.anchored else name) + "/"
        return any(rx.fullmatch(subject) for rx in self.regexes)


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
        anchored = "/" in line
        line = line.lstrip("/")
        specificity = sum(c not in _NOT_LITERAL for c in line)
        regexes = [re.compile(_translate(p), re.DOTALL) for p in _expand_braces(line)]
        rules.append(_Rule(negate, dir_only, anchored, specificity, regexes))
    return rules


def _expand_braces(pattern):
    """Expand the first `{...}` group (one without nested `{`), then the rest."""
    start = pattern.find("{")
    end = pattern.find("}", start + 1) if start >= 0 else -1
    if end < 0:
        return [pattern]
    head, body, tail = pattern[:start], pattern[start + 1:end], pattern[end + 1:]
    return [head + alt + rest for alt in body.split(",") for rest in _expand_braces(tail)]


def _translate(pattern):
    """Translate a glob into a regex matching a relative path plus a trailing "/"."""
    return "".join("(?:[^/]*/){0,3}" if seg == "**" else _translate_segment(seg) + "/"
                   for seg in pattern.split("/"))


def _translate_segment(seg):
    out = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            while i < len(seg) and seg[i] == "*":
                i += 1
            out.append("[^/]*")
            continue
        out.append("[^/]" if c == "?" else re.escape(c))
        i += 1
    return "".join(out)


# --- deciding -----------------------------------------------------------------

def _evaluate(node, path, rulesets, excluded, found):
    """Walk `node` (at `path`, excluded or not), collecting excluded files."""
    ignore_file = node.children.get(_fold(_IGNORE_FILE))
    if not excluded and isinstance(ignore_file, _File) and ignore_file.name == _IGNORE_FILE:
        with open(ignore_file.source, "rb") as f:
            rules = _parse(f.read().decode("utf-8"))
        rulesets = rulesets + [(len(path), rules)]
    for child in node.children.values():
        child_path = path + [child.name]
        is_dir = isinstance(child, _Dir)
        child_excluded = _decide(child_path, is_dir, rulesets)
        if child_excluded is None:
            child_excluded = excluded or (not is_dir and child.excluded_by_default)
        if is_dir:
            _evaluate(child, child_path, rulesets, child_excluded, found)
        elif child_excluded:
            found.append("/".join(child_path))


def _decide(path, is_dir, rulesets):
    """Return whether the rules exclude `path` itself, or None if none match it."""
    for depth, rules in reversed(rulesets):
        rel = "/".join(path[depth:])
        best = None
        for rule in rules:
            if rule.matches(rel, path[-1], is_dir) and (
                    best is None or rule.specificity >= best.specificity):
                best = rule
        if best is not None:
            return not best.negate
    return None
