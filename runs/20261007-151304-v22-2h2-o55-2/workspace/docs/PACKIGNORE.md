# packignore

`.packignore` files decide which files the packaging step leaves out. The
rules are implemented in pure Python by `snapshot/ignore.py`, which
reproduces the legacy `packignore` engine exactly; this page describes what
that engine actually did (the 1.4 docs from 2019 were incomplete and partly
wrong).

## Syntax

- Files are UTF-8. Lines are split on any Unicode line break (`\n`, `\r\n`,
  `\r`, `\v`, `\f`, ...) and stripped of surrounding whitespace. Blank lines
  are ignored.
- Lines starting with `;` are comments. **`#` is not a comment**: `#foo` is
  an ordinary pattern.
- `!pattern` re-includes what other patterns exclude. Only one `!` is
  removed, so `!!a` re-includes a file named `!a`.
- `*` matches any run of characters within a path segment, and `?` matches
  exactly one. `**` as a whole segment (`**/x`, `x/**/y`, `x/**`) matches any
  number of directories, including none; elsewhere it acts like `*`.
- `{a,b}` matches either alternative. A group runs from `{` to the next `}`
  (groups do not nest); a `{` with no `}` after it is literal.
- `\` and `[`/`]` have no special meaning; they match themselves.
- A pattern without a `/` matches a file or directory name at any depth. A
  pattern containing a `/` is relative to the directory holding the
  `.packignore` file; a leading `/` just anchors it there.
- A trailing `/` matches directories only. Excluding a directory excludes
  everything inside it, unless a pattern matches the file (or a deeper
  directory) more specifically; unlike `.gitignore`, files inside an
  excluded directory *can* be re-included.

## Precedence

For each file, the file itself and then each enclosing directory are tried,
deepest first. The first of these that any pattern matches decides. When
several patterns match the same path:

1. a pattern from a deeper `.packignore` wins;
2. otherwise the pattern with the higher score wins, where the score is the
   number of characters other than `* ? / { } ,`;
3. otherwise the later line wins.

So in

```
!important.tmp
*.tmp
```

`important.tmp` is kept: it scores 13 against 4 for `*.tmp`.

## Implicit exclusions

If no pattern matches the file itself, it is excluded anyway when it has any
executable permission bit set, or when its first line contains `@generated`.
A pattern naming the file (for example `!run.sh`) overrides this.

## Nested files

A `.packignore` applies to everything below its directory. It is not read at
all if its directory is excluded. A directory named `.packignore` (where the
file would be read) is an error, as is an undecodable `.packignore`.

## Tree quirks

- Only regular files count; symlinks are skipped. A `.git` directory, or a
  `.git` file, directly under the root is skipped.
- Names are compared caselessly (Unicode case folding and normalization), as
  on a case-insensitive file system. If two paths collide, the name met first
  (in `os.walk` order) is kept while the contents and permissions come from
  the one met last. A file colliding with a directory is an error.
- Patterns themselves match case-sensitively and without normalization.

## Limits

These are errors (`PackignoreError`), as they were in `packignore`:

- more than 5000 files in the tree, counted before case-collision merging;
- a path with more than 64 components, or longer than 955 UTF-8 bytes;
- any file named `.packignore`, even one that is never read, with more than
  2000 lines or a line longer than 1000 characters (counted after decoding
  with invalid UTF-8 replaced).

## Examples

```
; build output
build/
*.tmp
!important.tmp
```
