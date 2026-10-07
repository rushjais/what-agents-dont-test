"""Generate a frozen case set with git's answers baked in.

    python3 -m grader.build_cases --seed dev --n 500 --out cases/dev.jsonl

Freezing matters: once built, scoring never calls git, so every run on every
machine compares against exactly the same answers. The git version used is
recorded next to the cases.
"""

import argparse
import json
import os

from .generate import case_features, gen_case, gen_case_hard
from .oracle import git_version, ignored_by_git


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="set name, e.g. dev or hidden")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--profile", choices=["v1", "hard"], default="v1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for i in range(args.n):
            case_id = f"{args.seed}-{i:04d}"
            case = (gen_case_hard if args.profile == "hard" else gen_case)(case_id)
            case["id"] = case_id
            case["features"] = case_features(case)
            case["expected_ignored"] = ignored_by_git(case)
            f.write(json.dumps(case) + "\n")

    meta = {"seed": args.seed, "n": args.n, "profile": args.profile, "git_version": git_version()}
    with open(args.out.replace(".jsonl", ".meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"wrote {args.n} cases to {args.out} ({meta['git_version']})")


if __name__ == "__main__":
    main()
