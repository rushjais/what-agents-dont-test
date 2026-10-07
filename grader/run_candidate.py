"""Runs a candidate in its own process so a crash or hang can't take down the scorer.

Reads {"candidate": path, "roots": {case_id: dir}} on stdin, writes
{case_id: {"ok": bool, "result": [...] | "error": str}} on stdout.
"""

import importlib.util
import json
import os
import sys
import traceback


def load(path):
    """Import the candidate file. If it sits inside a package (e.g. an agent's
    snapshot/ignore.py), import it by dotted name so its relative imports work."""
    path = os.path.abspath(path)
    parts = [os.path.splitext(os.path.basename(path))[0]]
    top = os.path.dirname(path)
    while os.path.exists(os.path.join(top, "__init__.py")):
        parts.insert(0, os.path.basename(top))
        top = os.path.dirname(top)
    if len(parts) == 1:
        sys.path.insert(0, os.path.dirname(path))   # so sibling modules import
        spec = importlib.util.spec_from_file_location("candidate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    sys.path.insert(0, top)
    return importlib.import_module(".".join(parts))


def main():
    job = json.load(sys.stdin)
    mod = load(job["candidate"])

    out = {}
    for case_id, root in job["roots"].items():
        try:
            out[case_id] = {"ok": True, "result": list(mod.ignored_files(root))}
        except Exception:
            out[case_id] = {"ok": False, "error": traceback.format_exc(limit=3)}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
