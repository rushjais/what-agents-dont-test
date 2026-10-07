"""Random test-case generator.

A case is a small file tree plus one or more .gitignore files. The generator
only decides *what to try*; it never decides the right answer. The right
answer always comes from real git (see oracle.py).

Patterns are built from names that actually exist in the tree, so most lines
match something. Pure random strings would almost never match and the cases
would be trivially "nothing is ignored".
"""

import random
import re

DIR_NAMES = ["src", "build", "lib", "docs", "logs", "tmp", "a", "b", "foo",
             "node_modules", "out", "test"]

# All lowercase except README/Makefile, and no two names differ only by case:
# macOS filesystems are case-insensitive, so "a" and "A" would collide on disk.
FILE_NAMES = ["main.py", "util.py", "a.txt", "b.txt", "notes.md", "README",
              "debug.log", "err.log", "x.c", "x.o", "foo", "a", "data.json",
              ".env", ".hidden", "#notes.txt", "!important.txt", "f[1].txt",
              "build.sh", "Makefile"]


def gen_tree(rng, max_depth=3):
    files, dirs = [], []

    def walk(prefix, depth):
        used = set()
        for name in rng.sample(FILE_NAMES, rng.randint(1, 4)):
            used.add(name)
            files.append(prefix + name)
        if depth >= max_depth:
            return
        k = rng.choice([1, 2, 2, 3]) if depth == 0 else rng.choice([0, 0, 1, 1, 2])
        for d in rng.sample([d for d in DIR_NAMES if d not in used], k):
            used.add(d)
            dirs.append(prefix + d)
            walk(prefix + d + "/", depth + 1)

    walk("", 0)
    return files, dirs


# --- glob mutations of a single path component -----------------------------

def star_glob(rng, name):
    if "." in name.lstrip(".") and rng.random() < 0.6:
        return "*." + name.rsplit(".", 1)[1]          # debug.log -> *.log
    if len(name) > 2 and rng.random() < 0.5:
        return name[: rng.randint(1, len(name) - 1)] + "*"   # debug.log -> deb*
    return "*"


def question_glob(rng, name):
    i = rng.randrange(len(name))
    return name[:i] + "?" + name[i + 1:]


def class_glob(rng, name):
    i = rng.randrange(len(name))
    c = name[i]
    r = rng.random()
    if r < 0.4:
        cls = "[" + c + rng.choice("xyz") + "]"        # matches
    elif r < 0.7:
        cls = "[!" + rng.choice("xyz") + "]"           # negated class, matches unless c in xyz
    else:
        cls = "[a-m]"                                  # range, may or may not match
    return name[:i] + cls + name[i + 1:]


def escape_specials(rng, s):
    """Literal '[' in a name is a glob class unless escaped. Sometimes escape it."""
    if "[" in s and rng.random() < 0.6:
        s = s.replace("[", "\\[")
    return s


def gen_pattern(rng, base, files, dirs):
    under_f = [f[len(base):] for f in files if f.startswith(base)]
    under_d = [d[len(base):] for d in dirs if d.startswith(base) and d != base.rstrip("/")]
    if not under_f:
        return "*.log"

    is_dir = bool(under_d) and rng.random() < 0.35
    rel = rng.choice(under_d if is_dir else under_f)
    parts = rel.split("/")

    # basename-only pattern, or a path pattern containing a slash
    if len(parts) > 1 and rng.random() < 0.45:
        comps = parts[:]
    else:
        comps = [parts[-1]]

    comps[-1] = escape_specials(rng, comps[-1])
    r = rng.random()
    if r < 0.22:
        comps[-1] = star_glob(rng, parts[-1])
    elif r < 0.32:
        comps[-1] = question_glob(rng, parts[-1])
    elif r < 0.42:
        comps[-1] = class_glob(rng, parts[-1])
    elif r < 0.46:
        comps[-1] = comps[-1].upper() if comps[-1].islower() else comps[-1]  # case mismatch

    if len(comps) > 2 and rng.random() < 0.3:
        comps[rng.randrange(1, len(comps) - 1)] = "**"     # a/**/c
    pat = "/".join(comps)

    r = rng.random()
    if r < 0.18:
        pat = "/" + pat                                    # anchored to this .gitignore's dir
    elif r < 0.28:
        pat = "**/" + pat
    if is_dir:
        r = rng.random()
        if r < 0.5:
            pat += "/"
        elif r < 0.6:
            pat += "/**"
    elif rng.random() < 0.05:
        pat += "/"                                         # trailing slash on a file: must not match it

    # names starting with '#' or '!' need a backslash to be taken literally
    if pat[0] in "#!" and rng.random() < 0.7:
        pat = "\\" + pat

    if rng.random() < 0.25:
        pat = "!" + pat
    r = rng.random()
    if r < 0.07:
        pat += "   "                                       # unescaped trailing spaces are stripped
    elif r < 0.09:
        pat += "\\ "                                       # escaped trailing space is kept
    return pat


def gen_gitignore(rng, base, files, dirs):
    lines = []
    for _ in range(rng.randint(1, 6)):
        r = rng.random()
        if r < 0.08:
            lines.append("# " + rng.choice(["build output", "logs", "local stuff"]))
        elif r < 0.12:
            lines.append("")
        elif r < 0.20:
            lines.append(rng.choice(["*", "*.log", "!*.md", ".*", "*.o", "!README", "**", "/*"]))
        else:
            lines.append(gen_pattern(rng, base, files, dirs))
    text = "\n".join(lines)
    if rng.random() < 0.85:
        text += "\n"                                       # sometimes no trailing newline
    return text


def gen_case(seed):
    rng = random.Random(seed)
    files, dirs = gen_tree(rng)
    bases = [""] + [d + "/" for d in dirs if rng.random() < 0.3]
    gitignores = {b: gen_gitignore(rng, b, files, dirs) for b in bases}
    files = files + [b + ".gitignore" for b in bases]
    return {"files": sorted(files), "gitignores": gitignores}


def line_features(line):
    feats = set()
    s = line.rstrip("\n")
    if s == "":
        return {"blank"}
    if s.startswith("#"):
        return {"comment"}
    if s.startswith("!"):
        feats.add("negation")
        s = s[1:]
    if "\\" in s:
        feats.add("escape")
    if s.endswith(" "):
        feats.add("trailing_space")
    core = s.rstrip(" ")
    if core.startswith("/"):
        feats.add("leading_slash")
    if core.endswith("/"):
        feats.add("trailing_slash")
    if "/" in core.strip("/"):
        feats.add("middle_slash")
    if "**" in core:
        feats.add("double_star")
    elif "*" in core:
        feats.add("star")
    if "?" in core:
        feats.add("question")
    if "[" in core.replace("\\[", ""):
        feats.add("char_class")
    if core != core.lower() and core not in ("README", "!README"):
        feats.add("case")
    if re.search(r"[^/]\*\*|\*\*[^/]", core) and "***" not in core:
        feats.add("glued_double_star")
    if "***" in core:
        feats.add("triple_star")
    if "[:" in core:
        feats.add("posix_class")
    if s.startswith(" "):
        feats.add("leading_space")
    if s.endswith("\t") or s.endswith("\r"):
        feats.add("trailing_tab_or_cr")
    return feats


def case_features(case):
    feats = set()
    for base, text in case["gitignores"].items():
        if base:
            feats.add("nested_gitignore")
        if "\r\n" in text:
            feats.add("crlf")
        for line in text.split("\n"):
            feats |= line_features(line)
    return sorted(feats - {"blank"})


# --- "hard" profile -----------------------------------------------------------
# Added after run 1, where Opus 4.7's first draft scored 100% on the profile
# above. The agent's own fuzzer used a tiny alphabet, so patterns collided and
# combined in odd ways ("bc**/a"). This profile does the same, and adds syntax
# neither generator covered: glued/repeated **, odd character classes, escapes
# of ordinary characters, significant whitespace, CRLF line endings.

HARD_SPECIAL_NAMES = ["a b", " a", "a ", "a*", "[a]", "#a", "!a", "a\\b", "a.b", ".a"]

# Common forms are picked 3x as often as rare ones, so no single quirk (e.g. a
# reversed range crashing a regex compiler) decides a large share of cases.
HARD_CLASSES_COMMON = ["[ab]", "[!a]", "[^a]", "[a-b]", "[]a]", "[[:alpha:]]"]
HARD_CLASSES_RARE = ["[!]]", "[[:digit:]]", "[a", "[b-a]", "[a-]", "[\\]]"]
HARD_ESCAPES = ["\\*", "\\?", "\\[", "\\\\", "\\a", "\\ ", "\\#", "\\!"]


def hard_name(rng):
    if rng.random() < 0.12:
        return rng.choice(HARD_SPECIAL_NAMES)
    return "".join(rng.choice("ab") for _ in range(rng.randint(1, 3)))


def gen_tree_hard(rng, max_depth=5):
    files, dirs = [], []

    def walk(prefix, depth):
        used = set()
        for _ in range(rng.randint(1, 4)):
            n = hard_name(rng)
            if n not in used and n != ".gitignore":
                used.add(n)
                files.append(prefix + n)
        if depth >= max_depth:
            return
        k = rng.choice([1, 2, 2, 3]) if depth == 0 else rng.choice([0, 1, 1, 2])
        for _ in range(k):
            n = hard_name(rng)
            if n not in used:
                used.add(n)
                dirs.append(prefix + n)
                walk(prefix + n + "/", depth + 1)

    walk("", 0)
    return files, dirs


def hard_token(rng):
    r = rng.random()
    if r < 0.35:
        return rng.choice("ab")
    if r < 0.50:
        return "*"
    if r < 0.62:
        return rng.choice(["**", "**", "***"])
    if r < 0.70:
        return "?"
    if r < 0.84:
        return "/"
    if r < 0.93:
        return rng.choice(HARD_CLASSES_COMMON if rng.random() < 0.75 else HARD_CLASSES_RARE)
    return rng.choice(HARD_ESCAPES)


def gen_line_hard(rng, base, files, dirs):
    r = rng.random()
    if r < 0.4:
        line = gen_pattern(rng, base, files, dirs)          # name-based, from the v1 generator
    elif r < 0.93:
        line = "".join(hard_token(rng) for _ in range(rng.randint(1, 6)))
    else:
        line = rng.choice(["!", "/", "\\", "\\!", "#", " ", "!/", "**/", "/**/"])
    if rng.random() < 0.2:
        line = "!" + line
    r = rng.random()
    if r < 0.06:
        line = "  " + line                                  # leading spaces are significant
    elif r < 0.12:
        line += " \t"                                       # only trailing spaces are stripped
    elif r < 0.16:
        line += "\\"                                        # trailing backslash
    return line


def gen_case_hard(seed):
    rng = random.Random(seed)
    files, dirs = gen_tree_hard(rng)
    bases = [""] + [d + "/" for d in dirs if rng.random() < 0.4]
    gitignores = {}
    for b in bases:
        lines = [gen_line_hard(rng, b, files, dirs) for _ in range(rng.randint(1, 8))]
        eol = "\r\n" if rng.random() < 0.1 else "\n"
        text = eol.join(lines) + (eol if rng.random() < 0.85 else "")
        gitignores[b] = text
    files = files + [b + ".gitignore" for b in bases]
    return {"files": sorted(files), "gitignores": gitignores}
