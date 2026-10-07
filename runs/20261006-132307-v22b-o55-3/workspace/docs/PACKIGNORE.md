# packignore

`packignore` decides which files the packaging step leaves out. It reads
`.packignore` files from the project tree.

The original `packignore` service has been retired. `snapshot/ignore.py` is a
pure-Python reimplementation that matches its observed behaviour. That
behaviour differed from the old 1.4 documentation in several places; this page
describes what the engine actually does.

## Syntax

- `.packignore` files are UTF-8. Lines are split on any Unicode line break
  (`\n`, `\r\n`, `\r`, `\v`, `\f`, U+2028, ...).
- Surrounding whitespace (including Unicode spaces) is stripped from each line.
  Blank lines are ignored.
- Lines starting with `;` are comments. **`#` is not a comment character**:
  `#foo` is a pattern matching a file named `#foo`.
- A leading `!` re-includes what the pattern matches. Only one `!` is removed
  (`!!x` re-includes `!x`). There is no escape character: `\` is literal.
- A trailing `/` makes the pattern match directories only.
- A pattern containing a `/` (other than a trailing one) is relative to the
  directory holding the `.packignore` file. A leading `/` just anchors the
  pattern there. A pattern without a `/` matches a name at any depth.
- `*` matches any run of characters within a path segment, and `?` matches
  exactly one. `[`, `]` and `\` are literal; there are no character classes.
- A `**` segment (`**/x`, `a/**/b`, `a/**`) matches **zero to three** path
  segments, not an unlimited number. Repeated `**` segments add up
  (`**/**/x` reaches six levels deep). `**` inside a segment (`a**`)
  acts like `*`.
- Matching is case-sensitive.

## Which rule wins

Excluding a directory excludes everything inside it. For a file, the file's own
path is checked first, then its enclosing directories from the innermost
outwards. At the first path where any rule matches, one rule decides:

1. the rule from the deepest `.packignore` file,
2. then the most specific rule (most characters other than `*`, `?` and `/`),
3. then the rule that comes later in the file.

So `!a/x` re-includes `a/x` even if `a/` is excluded, wherever the two lines
appear. Also, `!keep.tmp` beats `*.tmp` in either order because it is more
specific.

## Nested files

A `.packignore` in a subdirectory applies to that subdirectory's contents. A
`.packignore` inside an excluded directory is not read. A `.packignore` that
is itself excluded is still read.

## Examples

```
; build output
build/
*.tmp
!important.tmp
```
