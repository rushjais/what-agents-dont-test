"""Score a candidate against a v2 case set, with a per-rule breakdown.

    python3 v2/grader/score.py CANDIDATE.py --cases v2/cases/dev.jsonl [--show 3] [--report out.json]

Same contract and strictness as v1 (exact set match per case, candidate run in
a subprocess with an empty PATH). The breakdown is by bucket: each case was
chosen to exercise one hidden rule (or none, "documented_only"), so a bucket's
pass rate says whether the candidate discovered that rule.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TASK = os.path.dirname(os.path.dirname(HERE))      # gitignore-task/, home of grader.run_candidate
sys.path.insert(0, HERE)
from generate import materialize  # noqa: E402


def run(candidate, cases, timeout):
    with tempfile.TemporaryDirectory() as tmp:
        roots = {}
        for c in cases:
            roots[c["id"]] = os.path.join(tmp, c["id"])
            materialize(c, roots[c["id"]])
        job = json.dumps({"candidate": os.path.abspath(candidate), "roots": roots})
        env = {**os.environ, "PATH": ""}
        try:
            proc = subprocess.run([sys.executable, "-m", "grader.run_candidate"], input=job,
                                  capture_output=True, text=True, timeout=timeout, env=env, cwd=TASK)
        except subprocess.TimeoutExpired:
            return {c["id"]: {"ok": False, "error": "timeout"} for c in cases}
        if proc.returncode != 0:
            return {c["id"]: {"ok": False, "error": proc.stderr[-2000:]} for c in cases}
        return json.loads(proc.stdout)


def score(candidate, cases, timeout=600):
    outputs = run(candidate, cases, timeout)
    rows = []
    for c in cases:
        out = outputs.get(c["id"], {"ok": False, "error": "missing"})
        expected = set(c["expected_ignored"])
        if out["ok"]:
            got = {p.removeprefix("./") for p in out["result"]}
            rows.append({"id": c["id"], "bucket": c["bucket"], "pass": got == expected,
                         "missing": sorted(expected - got), "extra": sorted(got - expected),
                         "error": None})
        else:
            rows.append({"id": c["id"], "bucket": c["bucket"], "pass": False, "missing": [],
                         "extra": [], "error": out["error"]})
    return rows


def summarize(rows):
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["bucket"]][0] += r["pass"]
        by[r["bucket"]][1] += 1
    passed = sum(r["pass"] for r in rows)
    return {"cases": len(rows), "passed": passed, "score": passed / len(rows) if rows else 0.0,
            "errors": sum(r["error"] is not None for r in rows),
            "by_rule": {k: {"passed": p, "cases": n, "rate": p / n} for k, (p, n) in sorted(by.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--cases", default=os.path.join(TASK, "v2", "cases", "dev.jsonl"))
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--report")
    args = ap.parse_args()

    cases = [json.loads(line) for line in open(args.cases)]
    rows = score(args.candidate, cases, args.timeout)
    s = summarize(rows)
    print(f"{args.candidate}: {s['passed']}/{s['cases']} = {s['score']:.1%}  (errors {s['errors']})")
    for k, v in s["by_rule"].items():
        print(f"  {k:<24}{v['rate']:>7.1%}  ({v['passed']}/{v['cases']})")
    shown = 0
    for c, r in zip(cases, rows):
        if shown >= args.show:
            break
        if not r["pass"]:
            shown += 1
            print(f"\n--- {c['id']} bucket={c['bucket']} rules={c['rules']}")
            for path, text in c["contents"].items():
                print(f"  {path}: {text!r}")
            if r["error"]:
                print(f"  ERROR {r['error'].strip().splitlines()[-1]}")
            print(f"  missing={r['missing']} extra={r['extra']}")
    if args.report:
        json.dump({"summary": s, "rows": rows}, open(args.report, "w"), indent=2)


if __name__ == "__main__":
    main()
