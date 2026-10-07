"""Ground truth: ask real git which files it ignores.

The question we ask git is "which untracked files would you skip?", via
`git ls-files --others --ignored --exclude-standard`. That is the behavior the
task's prompt promises to match.

Isolation matters more than it looks. Without it, the answer depends on the
machine running the grader, not on the case:
  - a global excludes file (~/.config/git/ignore or core.excludesFile) adds patterns
  - core.ignorecase=true (git's default on macOS) makes "*.LOG" match "debug.log"
  - repo templates can ship an info/exclude file with extra patterns
Each of those would be a grader bug: the expected answer would come from
something the agent cannot see.
"""

import os
import subprocess
import tempfile

GIT = ["git", "-c", "core.ignorecase=false", "-c", "core.excludesFile=" + os.devnull]


def git_env(home):
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "XDG_CONFIG_HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
    }


def materialize(case, root):
    """Write a case to disk: every file gets dummy content, .gitignore files get their text."""
    os.makedirs(root, exist_ok=True)
    for rel in case["files"]:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        base = rel[: -len(".gitignore")] if rel.endswith(".gitignore") else None
        with open(path, "w", newline="") as f:
            if base is not None and base in case["gitignores"]:
                f.write(case["gitignores"][base])
            else:
                f.write("x\n")


def _ls(root, env, *args):
    out = subprocess.run(GIT + ["ls-files", "-z", "--others", "--exclude-standard", *args],
                         cwd=root, env=env, check=True, capture_output=True).stdout
    return {p for p in out.decode().split("\0") if p}


def git_version():
    return subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()


def ignored_by_git(case):
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "repo")
        materialize(case, root)
        env = git_env(tmp)
        subprocess.run(GIT + ["init", "-q", "--template="], cwd=root, env=env,
                       check=True, capture_output=True)
        ignored = _ls(root, env, "--ignored")
        kept = _ls(root, env)

    # Self-check: git's two answers must split the file list exactly.
    # If they don't, the oracle is broken for this case and we refuse to use it.
    universe = set(case["files"])
    if ignored & kept or (ignored | kept) != universe:
        raise RuntimeError(
            f"oracle self-check failed: overlap={sorted(ignored & kept)} "
            f"missing={sorted(universe - ignored - kept)} extra={sorted((ignored | kept) - universe)}")
    return sorted(ignored)
