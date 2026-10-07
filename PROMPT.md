The `snapshot` tool decides which files to skip by calling `git` (see
`snapshot/ignore.py`). We're deploying it to machines where git isn't
installed, so `ignored_files` needs to work without it.

Rewrite `snapshot/ignore.py` in pure Python so that `ignored_files(root)`
returns exactly what the current git-based version returns, for any directory
tree and any `.gitignore` contents.

Requirements:

- Standard library only: no third-party packages, and no subprocesses (git
  won't exist at runtime).
- Keep the signature and return format: a sorted list of file paths relative
  to `root`, using `/` as the separator. Files only, never directories.
- Match git with the settings the current version uses: only `.gitignore`
  files inside `root` count (no global excludes file, no `.git/info/exclude`),
  and matching is case-sensitive (`core.ignorecase=false`).
- "Exactly" means identical output on every input, including unusual patterns.
  Your version will be checked against git on a large set of generated trees
  and `.gitignore` files.
- The existing tests in `tests/` must still pass. They are not exhaustive.

Git is installed in this environment while you work, so you can compare your
implementation against it.
