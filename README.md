# What agents don't test

An RL environment task for coding agents, built three times. Each version
grades an agent by **differential testing**: the agent rewrites one function
so it behaves exactly like a reference program, and a grader compares the two
on hundreds of hidden random inputs. No expected answer is written by hand.

**Write-up:** *link to be added*

## The finding

Agents test extensively, but only inside their own assumptions, and then
report that testing as proof they're done. Across two models and three task
versions, the failing runs each built a fuzzer, compared against the
reference, and reported a match, while missing exactly the behavior their
fuzzer never generated.

| Version | Reference | Opus 4.7 | Opus 5.5 |
|---|---|---|---|
| **v1** gitignore | real git | 0/4 solved (83–91% on the hard set) | 3/3 solved, ~12 min, by recalling git's `wildmatch.c` |
| **v2.1** invented tool | `packignore`, a black box | 0/2 (43%, 66%; budget cap) | 3/4 solved, 27–42 min |
| **v2.2** + non-path rules | `packignore` with content/permission rules | not run | **4/9 solved** (2/6 at 60 min, 2/3 at 2 h) |

Full details: [`UNDERSTANDING.md`](UNDERSTANDING.md) (v1) and
[`V2_DESIGN.md`](V2_DESIGN.md) (v2.x: rules, grader checks, QA log, every run).

## The task (all versions)

The agent works in a small Python tool, `snapshot`, which copies a project
and skips ignored files. `snapshot/ignore.py` currently asks a reference
program which files to skip. The prompt says that program won't exist at
deployment, so the agent must rewrite `ignored_files(root)` in pure Python
(standard library, no subprocesses, no network) to return exactly what the
reference returns. The reference stays available while the agent works, so it
can test itself.

- **v1** (`starter/`, `PROMPT.md`): the reference is git. Expected answers
  come from an isolated `git ls-files --ignored`.
- **v2.1** (`v2/`): the reference is `packignore`, an invented legacy tool.
  Its source never enters the sandbox; it runs as a server on the host and
  the agent gets a thin client. The README it ships with is incomplete and
  wrong in one place. Five rules are undocumented.
- **v2.2** (`v22/`): v2.1 plus two rules that don't depend on the path: files
  whose first line contains `@generated`, and executable files, are excluded
  by default. Evidence for both is in the agent's own repo.

## Layout

```
PROMPT.md, starter/       v1 task: what the agent sees
grader/                   v1 grader
  generate.py               random cases (realistic + "hard" profile)
  oracle.py                 expected answers from isolated git, with a self-check
  build_cases.py            freeze cases + answers to JSONL
  score.py                  exact-match scoring, candidate in a subprocess, git blocked
  static_check.py           flags non-stdlib imports, subprocess and network use
  minimize.py               shrinks a failing case to its root cause
baselines/                v1 baselines (git wrapper, naive fnmatch, pathspec)
cases/                    v1 dev/hidden sets (realistic + hard)

v2/, v22/                 v2.1 and v2.2, each self-contained:
  reference/                the hidden tool + tests showing each rule is discoverable
  server/                   the black-box oracle (HTTP, input limits, generic errors)
  starter/                  what the agent sees (snapshot, client, old README, clue files)
  PROMPT.md                 the task prompt
  grader/                   rule-tagged generator, balanced case builder, per-rule scorer
  baselines/                reference, README-only, one-rule-missed
  cases/                    dev and hidden sets

runner/
  run_attempt.py            one attempt: workspace, sandbox (local or Docker), grading
  Dockerfile                the agent sandbox image
  score_over_time.py        rebuilds each version of an agent's code from its transcript
  save_token.sh             stores a Claude Code token for Docker runs, no copy-paste

runs/                     every attempt: transcript, final code, diff, summary, report
```

## Running it

Requires Python 3.11+, git, and Docker for sandboxed runs. The graders are
standard library only.

```bash
# score a candidate on the v2.2 hidden set, with a per-rule breakdown
python3 v22/grader/score.py path/to/snapshot/ignore.py --cases v22/cases/hidden.jsonl

# check the graders against their baselines
python3 v22/grader/score.py v22/baselines/reference_true.py --cases v22/cases/hidden.jsonl   # 100%
python3 v22/grader/score.py v22/baselines/readme_only.py --cases v22/cases/hidden.jsonl      # ~18%

# run one agent attempt in Docker (builds on a Claude Code token)
docker build -t snapshot-task-agent runner/
runner/save_token.sh
python3 runner/run_attempt.py --label try1 --task v2.2 --sandbox docker --model claude-opus-5-5
```

## How the grader is kept honest

- **Answers come from a reference, never by hand.** v1's oracle isolates git
  from the host (fake home, no global excludes, case-sensitive, empty
  template) and refuses to answer unless git's ignored and not-ignored lists
  partition the files exactly.
- **Every hidden rule is discoverable.** v2's reference tests show each rule
  changing the answer on a 2–3 line input, and every rule has evidence in the
  environment.
- **Per-rule scoring.** Each hidden case is tagged by which rules change its
  answer when switched off; hidden sets hold 100 cases per rule.
- **No free reward.** Candidates run with git and the oracle unavailable; a
  static check flags subprocess and network use; the untouched starter scores 0%.
- **Invalid runs are kept and labeled,** not counted: runs hit by laptop
  sleep, a machine restart, oracle bugs, or harness bugs.

The QA logs in `UNDERSTANDING.md` and `V2_DESIGN.md` record more than twenty
grader and harness bugs found and fixed during the project, including an
oracle that froze when an agent probed it with pathological patterns.

## Authorship

Built with Claude Code as a coding agent under my direction. I set the
direction, made the design and scoping calls, and reviewed results; the code
and much of the prose were written by the agent.
