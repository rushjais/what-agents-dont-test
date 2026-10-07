"""Reference implementation of `packignore`, the invented legacy tool behind v2.

NEVER give this file to an agent. It runs on the host (oracle_server.py) and in
the grader; the agent only sees answers.

The behavior is documented in ../V2_DESIGN.md. Each undocumented rule can be
switched off, which is how the grader tags cases (a case "exercises" a rule if
switching the rule off changes the answer) and how the README-only baseline
is built.

Semantics, precisely:
  Parsing (per line): strip surrounding whitespace; skip blank lines; skip
  comment lines (';' really, '#' per the README); a leading '!' negates; a
  trailing '/' makes the pattern match directories only; a pattern containing
  '/' (after removing the trailing one) is anchored to its .packignore's
  directory, otherwise it matches a name at any depth below it. No escapes.
  Globs: '*' any run of non-'/' characters, '?' one non-'/' character, a whole
  segment '**' spans directories (at most 3 with the depth limit), '**' inside
  a segment acts like '*'. '{a,b}' alternation (no nesting; an unclosed '{'
  is literal).
  Precedence: among patterns matching a path, the winner has the deepest
  .packignore, then the most literal characters (specificity), then the latest
  line. With specificity off this is plain last-match-wins.
  Directories: a path with no matching pattern inherits its parent directory's
  status. With re-inclusion on, a '!' rule can rescue a path inside an excluded
  directory, but .packignore files inside excluded directories are not read.
  With it off (git-like), everything under an excluded directory is excluded.
"""

import os
from dataclasses import dataclass, field

IGNORE_FILE = ".packignore"


@dataclass(frozen=True)
class Rules:
    specificity: bool = True         # H1: most specific pattern wins (off: last match wins)
    depth_limit: int | None = 3      # H2: '**' spans at most this many dirs (None: unlimited)
    reinclude: bool = True           # H3: '!' works inside excluded dirs (off: git-like)
    braces: bool = True              # H4: '{a,b}' alternation (off: braces are literal)
    semicolon_comments: bool = True  # W1: ';' starts a comment (off: '#', as the README claims)


TRUE = Rules()
README_ONLY = Rules(specificity=False, depth_limit=None, reinclude=False, braces=False,
                    semicolon_comments=False)

# Rule name -> the Rules you get by switching just that rule off.
ABLATIONS = {
    "W1_semicolon_comments": Rules(semicolon_comments=False),
    "H1_specificity": Rules(specificity=False),
    "H2_depth_limit": Rules(depth_limit=None),
    "H3_reinclude": Rules(reinclude=False),
    "H4_braces": Rules(braces=False),
}


@dataclass
class Pattern:
    negate: bool
    dir_only: bool
    anchored: bool
    alts: list = field(default_factory=list)   # each alternative is a list of segments
    specificity: int = 0
    index: int = 0


def expand_braces(s):
    i = s.find("{")
    if i < 0:
        return [s]
    j = s.find("}", i)
    if j < 0:
        return [s]
    head, opts, tail = s[:i], s[i + 1:j].split(","), s[j + 1:]
    return [head + o + t for o in opts for t in expand_braces(tail)]


def parse(text, rules=TRUE):
    comment = ";" if rules.semicolon_comments else "#"
    pats = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or line.startswith(comment):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if not line:
            continue
        alts = expand_braces(line) if rules.braces else [line]
        specificity = sum(1 for c in line if c not in "*?/{},")
        pats.append(Pattern(negate, dir_only, anchored, [a.split("/") for a in alts],
                            specificity, index))
    return pats


def seg_match(glob, name):
    """'*' = any run of characters, '?' = exactly one, everything else literal.

    Linear-time wildcard matching (greedy with one backtrack point). The first
    version compiled each glob to a regex, and runs of '*' made Python's regex
    engine backtrack exponentially: an agent probing 'a*a*a*...' froze the
    oracle. Same semantics, no blowup.
    """
    i = j = 0
    star, mark = -1, 0
    while j < len(name):
        if i < len(glob) and glob[i] == "*":
            star, mark, i = i, j, i + 1
        elif i < len(glob) and (glob[i] == "?" or glob[i] == name[j]):
            i, j = i + 1, j + 1
        elif star >= 0:
            mark += 1
            i, j = star + 1, mark
        else:
            return False
    while i < len(glob) and glob[i] == "*":
        i += 1
    return i == len(glob)


def match_segments(pat, path, limit):
    """Match pattern segments against path segments; '**' spans up to `limit` dirs.

    Memoized on (pattern position, path position) so many '**' segments stay
    polynomial instead of branching exponentially.
    """
    memo = {}

    def go(i, j):
        key = (i, j)
        if key not in memo:
            if i == len(pat):
                r = j == len(path)
            elif pat[i] == "**":
                rest = len(path) - j
                most = rest if limit is None else min(limit, rest)
                r = any(go(i + 1, j + k) for k in range(most + 1))
            else:
                r = j < len(path) and seg_match(pat[i], path[j]) and go(i + 1, j + 1)
            memo[key] = r
        return memo[key]

    return go(0, 0)


def pattern_matches(p, segs, rules):
    for alt in p.alts:
        if p.anchored or len(alt) > 1:
            if match_segments(alt, segs, rules.depth_limit):
                return True
        elif seg_match(alt[0], segs[-1]):
            return True
    return False


def decide(stack, rel, is_dir, rules):
    """True = excluded, False = re-included, None = no pattern matches this path."""
    best = None
    for depth, (base, pats) in enumerate(stack):
        segs = rel[len(base):].split("/")
        for p in pats:
            if p.dir_only and not is_dir:
                continue
            if pattern_matches(p, segs, rules):
                key = (depth, p.specificity if rules.specificity else 0, p.index)
                if best is None or key > best[0]:
                    best = (key, p)
    return None if best is None else not best[1].negate


def ignored_files(root, rules=TRUE):
    """Sorted '/'-separated paths, relative to root, of files packignore excludes."""
    out = []

    def walk(rel_dir, stack, dir_excluded):
        abs_dir = os.path.join(root, rel_dir)
        names = sorted(os.listdir(abs_dir))
        if IGNORE_FILE in names and not dir_excluded:
            with open(os.path.join(abs_dir, IGNORE_FILE), newline="") as f:
                stack = stack + [(rel_dir, parse(f.read(), rules))]
        for name in names:
            if rel_dir == "" and name == ".git":
                continue
            rel = rel_dir + name
            full = os.path.join(root, rel)
            is_dir = os.path.isdir(full) and not os.path.islink(full)
            if dir_excluded and not rules.reinclude:
                excluded = True
            else:
                d = decide(stack, rel, is_dir, rules)
                excluded = dir_excluded if d is None else d
            if is_dir:
                walk(rel + "/", stack, excluded)
            elif excluded:
                out.append(rel)

    walk("", [], False)
    return sorted(out)
