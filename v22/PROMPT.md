The `snapshot` tool decides which files to skip by calling `packignore`, our
legacy exclusion engine (see `snapshot/ignore.py` and `tools/packignore`).
`packignore` is being shut down and its source code is lost, so
`ignored_files` needs to work without it.

Rewrite `snapshot/ignore.py` in pure Python so that `ignored_files(root)`
returns exactly what `packignore` returns, for any directory tree and any
`.packignore` contents.

Requirements:

- Standard library only: no third-party packages, no subprocesses, and no
  network access (`packignore` won't exist at runtime).
- Keep the signature and return format: a sorted list of file paths relative
  to `root`, using `/` as the separator. Files only, never directories.
- "Exactly" means identical output on every input, including unusual
  patterns. Your version will be checked against `packignore` on a large set
  of generated trees and `.packignore` files.
- `docs/PACKIGNORE.md` is the old documentation. It may be incomplete or out
  of date. Where it disagrees with `packignore`, `packignore` is right.

`packignore` is still running while you work: `tools/packignore ROOT` prints
what it excludes for any tree, so you can test your implementation against it.
