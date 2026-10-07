# packignore

*Internal build tooling docs. Originally written for packignore 1.4 (2019);
corrected to match the engine's actual behaviour, which `snapshot/ignore.py`
now reimplements in pure Python.*

`packignore` decides which files the packaging step leaves out. It reads
`.packignore` files from the project tree.

## Syntax

- One pattern per line. Lines are split on any line break Python's
  `str.splitlines()` recognises (`\n`, `\r\n`, `\r`, `\v`, `\f`, `\x1c`–`\x1e`,
  `\x85`, ` `, ` `), then stripped of leading and trailing
  whitespace. Blank lines are ignored.
- There are **no comments**: `#` is an ordinary character. There are no
  escapes either: `\` is an ordinary character.
- `*` matches any run of characters within a path segment, and `?` matches
  exactly one. `[` and `]` are ordinary characters. `**` inside a segment
  (e.g. `a**b`) is the same as `*`. A segment that is exactly `**` matches
  **zero to three** directories (so `**/x` matches `x`, `a/x`, `a/b/x` and
  `a/b/c/x`, but not `a/b/c/d/x`).
- A trailing `/` (one or more) matches directories only. Excluding a
  directory excludes everything inside it, unless re-included (see below).
- Leading `/`s are removed. A pattern that contains a `/` (other than
  trailing ones) is relative to the directory holding the `.packignore`
  file; otherwise it matches a file or directory name at any depth below it.
- `!pattern` re-includes something. Only the leading `!` is removed;
  `! x` re-includes `" x"`.

## How a path is decided

Every directory and file is decided on its own, top-down:

1. Collect the rules (from all `.packignore` files in effect) that match the
   path itself. If none match, the path inherits its parent directory's
   decision (the root is included).
2. Otherwise one rule decides, chosen by, in order:
   - the deepest `.packignore` file wins;
   - then the pattern with the most literal characters (anything other
     than `*`, `?` and `/`) wins;
   - then the later line wins.

So a file can be re-included inside an excluded directory (`build/` then
`!build/keep`), and `!*` does not override `a` (fewer literal characters).

## Nested files

A `.packignore` in a subdirectory applies to that subdirectory's contents,
and its rules take precedence over those of its ancestors. It is only read if
its directory is not excluded. A `.git` directory directly under the root is
skipped.

## Examples

```
build/
*.tmp
!important.tmp
```
