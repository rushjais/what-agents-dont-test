"""Shrink a failing case to the fewest .gitignore lines that still make a candidate disagree with git.

    python3 -m grader.minimize CANDIDATE.py --cases cases/hard-hidden.jsonl --report reports/x.json --out reports/x.min.json

Most cases contain many features, so "which rule did it get wrong?" isn't
visible from the case itself. Greedy line deletion (a simple form of delta
debugging) answers it: drop one line at a time, keep the drop if the candidate
still disagrees with git, repeat until no single line can go.

Calls real git for every attempt, so this is slow (about a second per try).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

from .oracle import ignored_by_git, materialize

SHIM = """
import importlib.util, json, sys
sys.path.insert(0, sys.argv[2])
from grader.run_candidate import load
mod = load(sys.argv[1])
try:
    print(json.dumps({"ok": True, "result": sorted(mod.ignored_files(sys.argv[3]))}))
except Exception as e:
    print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
"""


def candidate_answer(candidate, case, task_dir):
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "case")
        materialize(case, root)
        out = subprocess.run([sys.executable, "-c", SHIM, os.path.abspath(candidate), task_dir, root],
                             capture_output=True, text=True, timeout=60, env={**os.environ, "PATH": ""})
        return json.loads(out.stdout.strip().splitlines()[-1])


def disagrees(candidate, case, task_dir):
    got = candidate_answer(candidate, case, task_dir)
    return not got["ok"] or set(got["result"]) != set(ignored_by_git(case)), got


def with_lines(case, lines_by_base):
    eols = {b: ("\r\n" if "\r\n" in t else "\n") for b, t in case["gitignores"].items()}
    gi = {b: eols[b].join(ls) + (eols[b] if ls else "") for b, ls in lines_by_base.items()}
    return {"files": case["files"], "gitignores": gi}


def minimize(candidate, case, task_dir):
    lines = {}
    for b, t in case["gitignores"].items():
        eol = "\r\n" if "\r\n" in t else "\n"
        ls = t.split(eol)
        if ls and ls[-1] == "":
            ls = ls[:-1]
        lines[b] = ls
    changed = True
    while changed:
        changed = False
        for b in list(lines):
            i = 0
            while i < len(lines[b]):
                trial = {k: (v[:i] + v[i + 1:] if k == b else v) for k, v in lines.items()}
                if disagrees(candidate, with_lines(case, trial), task_dir)[0]:
                    lines = trial
                    changed = True
                else:
                    i += 1
    small = with_lines(case, lines)
    _, got = disagrees(candidate, small, task_dir)
    expected = set(ignored_by_git(small))
    return {
        "id": case["id"],
        "lines": {b or "(root)": ls for b, ls in lines.items() if ls},
        "error": None if got["ok"] else got["error"],
        "missing": sorted(expected - set(got.get("result", []))) if got["ok"] else [],
        "extra": sorted(set(got.get("result", [])) - expected) if got["ok"] else [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--report", required=True, help="score.py --report output for this candidate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-errors", action="store_true", help="only minimize wrong answers, not crashes")
    args = ap.parse_args()

    task_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cases = {c["id"]: c for c in map(json.loads, open(args.cases))}
    rows = json.load(open(args.report))["rows"]
    failing = [r["id"] for r in rows if not r["pass"] and not (args.skip_errors and r["error"])]
    results = []
    for n, cid in enumerate(failing, 1):
        res = minimize(args.candidate, cases[cid], task_dir)
        results.append(res)
        print(f"[{n}/{len(failing)}] {cid}: {json.dumps(res['lines'])}"
              f"{'  ERROR ' + res['error'] if res['error'] else ''}", flush=True)
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
