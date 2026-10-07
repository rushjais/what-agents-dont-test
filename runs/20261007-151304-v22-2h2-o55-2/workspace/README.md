# snapshot

Copy a project tree, skipping the files its `.packignore` files exclude.

```bash
python3 -m snapshot path/to/project path/to/backup
```

Requires Python 3.11+, standard library only.

Exclusion rules are documented in [docs/PACKIGNORE.md](docs/PACKIGNORE.md) and
implemented in `snapshot/ignore.py`, a pure-Python port of the legacy
`packignore` engine. To see what is excluded for a tree:

```bash
python3 -c 'import sys; from snapshot.ignore import ignored_files; print(*ignored_files(sys.argv[1]), sep="\n")' path/to/project
```
