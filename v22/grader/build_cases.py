"""Build a balanced, frozen v2 case set.

    python3 v2/grader/build_cases.py --seed hidden --per-rule 100 --out v2/cases/hidden.jsonl

Generates a large pool, tags each case by the rules it exercises, then picks
`per-rule` cases for each rule plus `per-rule` "documented-only" cases (no
hidden rule matters). Cases exercising exactly one rule are preferred, so a
failure can be attributed to that rule. No single rule can dominate the score.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate import gen_case, packignore, tag  # noqa: E402

DOC_ONLY = "documented_only"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True)
    ap.add_argument("--per-rule", type=int, default=100)
    ap.add_argument("--pool", type=int, default=6000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    buckets = {name: [] for name in list(packignore.ABLATIONS) + [DOC_ONLY]}
    for i in range(args.pool):
        cid = f"{args.seed}-{i:05d}"
        case = gen_case(cid)
        truth, tags = tag(case)
        case.update(id=cid, rules=tags, expected_ignored=truth)
        if not tags:
            buckets[DOC_ONLY].append(case)
        for t in tags:
            buckets[t].append(case)

    rng = random.Random(args.seed)
    chosen, seen = [], set()
    for name, pool in buckets.items():
        pool = sorted(pool, key=lambda c: (len(c["rules"]), rng.random()))   # single-rule first
        picked = [c for c in pool if c["id"] not in seen][: args.per_rule]
        if len(picked) < args.per_rule:
            sys.exit(f"only {len(picked)} cases for {name}; raise --pool")
        for c in picked:
            c["bucket"] = name
            seen.add(c["id"])
        chosen += picked

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for c in chosen:
            f.write(json.dumps(c) + "\n")
    counts = {n: len(b) for n, b in buckets.items()}
    single = sum(len(c["rules"]) <= 1 for c in chosen)
    print(f"wrote {len(chosen)} cases to {args.out}; pool counts {counts}; "
          f"{single}/{len(chosen)} exercise at most one rule")


if __name__ == "__main__":
    main()
