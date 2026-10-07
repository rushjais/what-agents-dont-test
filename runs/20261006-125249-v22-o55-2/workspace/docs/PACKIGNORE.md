# packignore

*Internal build tooling docs. Last updated for packignore 1.4 (2019).*

`packignore` decides which files the packaging step leaves out. It reads
`.packignore` files from the project tree.

## Syntax

- One pattern per line. Blank lines are ignored.
- Lines starting with `#` are comments.
- `*` matches any run of characters within a path segment, and `?` matches
  exactly one. `**` matches across directories.
- A pattern without a `/` matches a file or directory name at any depth.
  A pattern containing a `/` is relative to the directory holding the
  `.packignore` file. A leading `/` anchors a pattern to that directory.
- A trailing `/` matches directories only. Excluding a directory excludes
  everything inside it.
- `!pattern` re-includes something an earlier pattern excluded.

## Nested files

A `.packignore` in a subdirectory applies to that subdirectory's contents.

## Examples

```
# build output
build/
*.tmp
!important.tmp
```
