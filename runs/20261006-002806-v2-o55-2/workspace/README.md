# snapshot

Copy a project tree, skipping the files its `.packignore` files exclude.

```bash
python3 -m snapshot path/to/project path/to/backup
```

Requires Python 3.11+, standard library only.

Exclusion rules follow the legacy `packignore` engine, reimplemented in
`snapshot/ignore.py`; see [docs/PACKIGNORE.md](docs/PACKIGNORE.md).
