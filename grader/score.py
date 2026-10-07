"""Score a candidate implementation against a frozen case set.

    python3 -m grader.score baselines/naive_fnmatch.py --cases cases/dev.jsonl --show 3

Contract the candidate must meet:
    ignored_files(root: str) -> iterable of str
      root contains the files and .gitignore files of one case and no .git dir.
      Return the POSIX paths, relative to root, of every *file* git would ignore.
      Do not list directories.

A case passes only if the returned set equals git's set exactly. The headline
score is the fraction of cases passed. Partial credit per file is reported too,
but only as a diagnostic.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict

from .oracle import materialize


def normalize(paths):
    # Only strip a leading "./". Backslashes are NOT converted to "/": on POSIX a
    # backslash is a legal filename character (the hard profile has a file "a\\b"),
    # and the contract asks for "/"-separated paths already.
    return {p.removeprefix("./") for p in paths}


def run(candidate, cases, timeout, allow_git=False):
    with tempfile.TemporaryDirectory() as tmp:
        roots = {}
        for c in cases:
            roots[c["id"]] = os.path.join(tmp, c["id"])
            materialize(c, roots[c["id"]])
        job = json.dumps({"candidate": os.path.abspath(candidate), "roots": roots})
        # The task's premise is that git is unavailable, so candidates run with an
        # empty PATH. This blocks `subprocess.run(["git", ...])` but not an absolute
        # path like /usr/bin/git; the real sandbox must not have git at all.
        env = dict(os.environ)
        if not allow_git:
            env["PATH"] = ""
        try:
            proc = subprocess.run([sys.executable, "-m", "grader.run_candidate"], input=job,
                                  capture_output=True, text=True, timeout=timeout, env=env,
                                  cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except subprocess.TimeoutExpired:
            return {c["id"]: {"ok": False, "error": "timeout"} for c in cases}
        if proc.returncode != 0:
            err = proc.stderr[-2000:]
            return {c["id"]: {"ok": False, "error": err} for c in cases}
        return json.loads(proc.stdout)


def score(candidate, cases, timeout, allow_git=False):
    outputs = run(candidate, cases, timeout, allow_git)
    rows = []
    for c in cases:
        out = outputs.get(c["id"], {"ok": False, "error": "missing"})
        expected = set(c["expected_ignored"])
        if out["ok"]:
            got = normalize(out["result"])
            missing, extra = sorted(expected - got), sorted(got - expected)
            universe = set(c["files"])
            wrong = len(missing) + len(extra)
            rows.append({"id": c["id"], "pass": wrong == 0, "missing": missing, "extra": extra,
                         "file_acc": 1 - wrong / max(len(universe), 1), "error": None})
        else:
            rows.append({"id": c["id"], "pass": False, "missing": [], "extra": [],
                         "file_acc": 0.0, "error": out["error"]})
    return rows


def summarize(cases, rows):
    n = len(rows)
    passed = sum(r["pass"] for r in rows)
    by_feat = defaultdict(lambda: [0, 0])
    for c, r in zip(cases, rows):
        for f in c["features"]:
            by_feat[f][1] += 1
            by_feat[f][0] += r["pass"]
    return {
        "cases": n,
        "passed": passed,
        "score": passed / n if n else 0.0,
        "file_accuracy": sum(r["file_acc"] for r in rows) / n if n else 0.0,
        "errors": sum(r["error"] is not None for r in rows),
        "by_feature": {f: {"passed": p, "cases": t, "rate": p / t}
                       for f, (p, t) in sorted(by_feat.items())},
    }


def show_failure(case, row):
    print(f"\n--- {case['id']}  features={case['features']}")
    for base, text in case["gitignores"].items():
        print(f"  {base or '(root)'}.gitignore:")
        for line in text.split("\n"):
            print(f"    | {line!r}")
    if row["error"]:
        print(f"  ERROR: {row['error'].strip().splitlines()[-1]}")
    if row["missing"]:
        print(f"  git ignores, candidate didn't: {row['missing']}")
    if row["extra"]:
        print(f"  candidate ignores, git doesn't: {row['extra']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--cases", default="cases/dev.jsonl")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--show", type=int, default=0, help="print N failing cases")
    ap.add_argument("--report", help="write full JSON report here")
    ap.add_argument("--allow-git", action="store_true",
                    help="leave git on PATH (only for the git_wrapper plumbing check)")
    args = ap.parse_args()

    with open(args.cases) as f:
        cases = [json.loads(line) for line in f]
    rows = score(args.candidate, cases, args.timeout, args.allow_git)
    summary = summarize(cases, rows)

    print(f"{args.candidate}: {summary['passed']}/{summary['cases']} cases "
          f"= {summary['score']:.1%}   (file-level accuracy {summary['file_accuracy']:.1%}, "
          f"errors {summary['errors']})")
    print(f"  {'feature':<18}{'pass rate':>10}{'cases':>8}")
    for feat, s in summary["by_feature"].items():
        print(f"  {feat:<18}{s['rate']:>10.1%}{s['cases']:>8}")

    shown = 0
    for c, r in zip(cases, rows):
        if shown >= args.show:
            break
        if not r["pass"]:
            show_failure(c, r)
            shown += 1

    if args.report:
        with open(args.report, "w") as f:
            json.dump({"summary": summary, "rows": rows}, f, indent=2)


if __name__ == "__main__":
    main()
