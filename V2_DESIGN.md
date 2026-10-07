# v2 design: black-box behavior cloning

**Status (2026-10-06):** decisions made (all 4 hidden rules, no example
tests, keep the wrong comment rule) and built. See "Build notes" at the end.

## Why v2

v1 (gitignore) results: Opus 4.7 failed 4/4 runs, Opus 5.5 solved 3/3 in about
12 minutes. Opus 5.5 succeeded by **recalling git's source** (`wildmatch.c`)
and porting it. Any task whose spec is a famous open-source behavior has this
weakness: it tests memory, not engineering.

v1 also showed *why* Opus 4.7 failed: its self-tests only covered syntax it
already knew about, so it couldn't find its own blind spots.

v2 removes memory as an option and makes that weakness the whole task:
**the behavior is invented, so the only way to learn it is to run
experiments.**

## The story the agent sees

Same shape as v1, so the two are comparable:

> `snapshot` decides what to skip using `.packignore` files, by calling
> `packignore`, a legacy internal tool. The tool is being decommissioned and
> its source is lost. Reimplement `ignored_files(root)` in pure Python with
> **identical behavior** to `packignore`. The old README is included. It
> may be incomplete or out of date. Where they disagree, the tool is right.
> The tool remains available while you work.

That's realistic: replacing a legacy binary whose docs have drifted is common
real-world work.

## The rules

Everything below is invented, so no model has seen it. The **documented**
rules go in the README the agent gets. The **undocumented** ones are true
behavior the README doesn't mention. One rule is **documented wrong**.

### Documented (in the README the agent gets)

| # | Rule |
|---|---|
| D1 | One pattern per line. Blank lines are ignored. |
| D2 | `*` and `?` match within one path segment; `**` matches across directories. |
| D3 | A pattern with no `/` matches a name at any depth. A pattern with a `/` is relative to the directory containing the `.packignore`. |
| D4 | `!pattern` re-includes something an earlier pattern excluded. |
| D5 | `.packignore` files in subdirectories apply to their own subtree. |

### Documented wrong

| # | README says | Truth |
|---|---|---|
| W1 | Lines starting with `#` are comments | Comments start with `;`. A `#` line is an ordinary pattern. |

### Undocumented (the agent must discover these)

| # | Truth | Why it's a good test |
|---|---|---|
| H1 | **Most specific pattern wins, not the last one.** Specificity = number of literal (non-wildcard) characters; ties go to the later line. A deeper `.packignore` beats a shallower one regardless. | Contradicts the gitignore-style "last match wins" every model will assume. Discoverable with two-line experiments. |
| H2 | **`**` spans at most 3 directory levels.** | A "legacy recursion limit." Only visible with deep trees, so an agent has to think to test depth. |
| H3 | **Re-inclusion inside an excluded directory works** (unlike git), but `.packignore` files inside an excluded directory are not read. | Half like git, half not. Tests whether the agent checks rather than assumes. |
| H4 | **`{a,b}` brace alternation** is supported. | Syntax that's absent from the docs. Only found if the agent tries syntax beyond what's documented. |

## Architecture: keeping the oracle a true black box

If the reference implementation is inside the agent's sandbox, even compiled,
the agent can decompile or read it. So **it never enters the sandbox**:

- The reference implementation runs as a small **server on the host**.
- The sandbox gets only a thin `packignore` client that sends a folder's
  `.packignore` files and file list to the server and prints the answer.
- The agent can query it as much as it likes, but can't see how it works.

The grader uses the same reference implementation directly to freeze the
hidden answers, the same way v1 used git.

## Fairness checklist (to verify before any run)

- [ ] Every hidden rule changes the answer on some *small* input (≤ 3 lines,
      ≤ 5 files), so careful experiments can find it.
- [ ] The README says plainly that it may be incomplete or wrong and that the
      tool is authoritative.
- [ ] The prompt says "identical behavior, checked on many generated trees."
- [ ] Hidden cases are spread evenly across rules, so no single rule dominates
      the score. (v1 lesson: `[b-a]` was worth ~5.6 points by itself.)
- [ ] Per-rule scoring, so the failure analysis can say exactly which rules
      each agent discovered.
- [ ] The reference implementation has its own tests, so we know it does what
      this document says.

## Scoring

- Hidden set: cases tagged by which rules they exercise, balanced across D, W
  and H rules, plus "plain" cases.
- Report: overall pass rate, **per-rule pass rate**, and "solved" (zero
  disagreements).
- The headline for the write-up is **which undocumented rules each model
  discovered**, which directly measures the v1 failure mode.

## Open questions for review

1. Are 4 undocumented rules the right number? Fewer makes it easier; more
   makes it more of a puzzle than a job.
2. Is H2 (depth limit 3) too obscure? It's the hardest to stumble on.
3. Should the agent get some example inputs and outputs, or only the README
   and the tool?

## Build notes

**Layout**

```
v2/reference/packignore.py       the hidden tool (never enters the sandbox)
v2/reference/test_packignore.py  13 tests: documented rules + one small example per hidden rule
v2/server/oracle_server.py       serves the reference over HTTP on the host
v2/starter/                      what the agent gets: snapshot/, tools/packignore (client),
                                 docs/PACKIGNORE.md (the old README), README.md
v2/PROMPT.md                     the task prompt
v2/grader/                       generate + tag (generate.py), balanced sets (build_cases.py),
                                 per-rule scorer (score.py)
v2/baselines/                    reference_true, readme_only, one_rule_missed
v2/cases/                        dev.jsonl (300 = 50 per bucket), hidden.jsonl (600 = 100 per bucket)
```

Run with `python3 runner/run_attempt.py --label v2-1 --task v2 --sandbox docker`.

**Grader checks**

| Check | Result |
|---|---|
| Reference implementation as candidate | 100% (scoring plumbing works) |
| README-only baseline | 24.7% on dev: 98% on documented-only, 0% on W1/H3/H4, 22–28% on H1/H2 |
| One rule switched off | fails its own bucket (0%), passes the others, except H2's bucket (80–88% when H3 or H4 is off, because H2 cases are rare and some also exercise them) |
| Every hidden rule changes the answer on a ≤ 3-line input | yes (test_packignore.py, `Hidden` tests) |
| Untouched starter with the oracle stopped | 0% |
| Container reaches the host oracle | yes, via host.docker.internal |

**QA log (v2)**

| # | Issue | Fix |
|---|---|---|
| 1 | Scorer loaded a lone candidate file without its folder on `sys.path`, so sibling imports failed (all baselines errored) | `run_candidate.load` adds the file's directory |
| 2 | The untouched starter calls the client with Python's absolute path, so v1's empty-PATH defense doesn't block it: with the oracle running, doing nothing would score 100% | runner stops the oracle before grading; static check flags network modules (`urllib`, `http`, `socket`, ...) as well as `subprocess` |
| 3 | The old README says "excluding a directory excludes everything inside it", which H3 contradicts | intentional: it's part of what the README gets wrong. Noted here so it's a deliberate choice, not an accident |
| 4 | H2 (depth limit) is rare in random trees (~2–3% of cases) | larger pool for the hidden set; H2 bucket accepts some multi-rule cases |
| 5 | **Oracle froze under agent probing.** Opus 5.5 (pilot run v2-o55-1) deliberately probed for hidden limits; patterns like `a*a*a*...` (30 stars) and 300 `*` in a row made the regex-based matcher backtrack exponentially. The server runs in one Python process, so one stuck request froze it for the rest of the run, and the agent lost its only test tool: an environment fault | Replaced the regex with a linear-time wildcard matcher and memoized `**` matching. Verified identical answers to the old matcher on 250,000 random inputs and on all 900 frozen cases; the freezing probes now take ~0 s |
| 6 | **Oracle leaked internals.** A tree with `build` as both a file and a directory returned a raw Python error containing a temp path on the host and hints about how the oracle works. All 4 pilot runs saw it | Input validation with plain-language errors (`'build' is both a file and a directory`); unexpected errors return only "internal error". Size limits (1,000 chars per line, 2,000 lines, 64 levels) far above any hidden case, with clear messages |

**Pilot runs (v2-*) are not reported as results.** All four ran against the
flawed oracle (#5, #6). Their results are kept in `runs/` as pilot data:
Opus 5.5 scored 94.7% and 74.8%, and both missed `;` comments; one also missed
braces entirely after reporting ~6,500 random trees matched. The two Opus 4.7
pilot runs were stopped partway when the flaws were found. Clean reruns are
labeled v2b-*.

## Change log

**v2.1 (2026-10-06): evidence for the `;` comment rule.** In all 4 Opus 5.5
runs (2 pilot, 2 clean), every failure traced to one rule: W1, `;` starts a
comment. Each agent tested that `#` isn't a comment, concluded there are no
comments, and never tried another character. Nothing in the environment
pointed to `;`; the only route was guessing characters, which is close to "the
grader checks something the agent had no reason to look for." Fix: the starter
repo now has its own legacy `.packignore` at its root, using `; ...` comment
lines. That's realistic (legacy repos carry old config) and turns W1 from a
guessing game into "did the agent notice evidence that contradicts the docs?"
It's a dotfile, so a casual `find -not -path '*/.*'` listing skips it, as two
pilot agents' listings did.

Results before this change (v2b-*) are reported as v2.0; runs after it are
labeled v2c-*.

**Laptop sleep (2026-10-06).** The two v2.0 Opus 4.7 runs (v2b-o47-*) ran
overnight while the Mac slept. The 60-minute limit used a clock that pauses
during sleep, so they resumed hours later with API errors (373 and 413 minutes
of wall time; 30.2% and 45.3%). Both are marked invalid. Fix: the runner keeps
the Mac awake with `caffeinate` for the whole run and enforces the limit on
wall-clock time.

**Laptop sleep, again (2026-10-06 08:10).** All four v2.1 runs (v2c-*) were
killed: the Mac slept about 20 minutes in, and on wake the wall-clock limit had
passed. `caffeinate -ims` prevents idle sleep but not lid-close sleep, and
system-sleep prevention only applies on AC power. All four are invalid (0/600,
no final code written). One early sign: v2c-o55-2 ran `cat .packignore`, so
it found the clue file. Before rerunning: plug in, keep the lid open.

**Background commands in headless mode (2026-10-06).** v2d-o55-1 started two
fuzz batches as background commands and ended its turn "waiting to be
notified". In `claude -p` the session ends with the turn, so the run stopped
mid-verification after 6.5 minutes (66.7%: found `;` via the clue, but missed
braces and the depth limit, which its unfinished fuzzing might have caught).
Harness fault, marked invalid. Fix: `--append-system-prompt` tells the agent
it's running non-interactively and should keep commands in the foreground. It
describes the harness only, not the task. Only one earlier run ended this way
(pilot v2-o55-1, already invalid).

**v2.1 results (v2d-*, 2026-10-06 10:09–10:51)**

| Run | Model | Score | Notes |
|---|---|---|---|
| v2d-o55-1 | Opus 5.5 | 66.7% | **invalid**: ended its turn waiting on background fuzzing (harness fault, fixed) |
| v2d-o55-2 | Opus 5.5 | **100% (600/600)** | stopped by us at 42 min (laptop had to close) while still verifying; its code at that point solves every rule, including `;` via the clue |
| v2d-o47-1 | Opus 4.7 | 43.0% | valid; hit the $10 budget at 30 min |
| v2d-o47-2 | Opus 4.7 | 65.7% | valid; hit the $10 budget at 39 min; missed braces and the depth limit |

**v2.1 results, with the harness fix (v2e-*, 2026-10-06 11:31–12:32)**

| Run | Model | Score | Time | Cost | Notes |
|---|---|---|---|---|---|
| v2e-o55-2 | Opus 5.5 | **100%** | 27 min | $3.93 | read the clue file |
| v2e-o55-3 | Opus 5.5 | **100%** | 31 min | $3.64 | |
| v2e-o55-1 | Opus 5.5 | **0%** | 60 min (time limit) | n/a | valid fail: mid-refactor, its `ignore.py` called an undefined helper (`_is_assigned`), so every case crashed. Its last ~10 minutes went to polling a long experiment that Claude Code had auto-backgrounded (commands over 2 minutes are moved to the background), so it never got back to fix the code |

## Summary: valid v2.1 runs

| Model | Valid runs | Solved | Scores | Typical time |
|---|---|---|---|---|
| Opus 5.5 | 4 (v2d-o55-2, v2e-o55-1/2/3) | **3** | 100, 100, 100, 0 (timed out with broken code) | 27–42 min |
| Opus 4.7 | 2 (v2d-o47-1/2) | 0 | 43.0, 65.7 (both hit the $10 budget) | 30–39 min |

**Reading this:**
- **v2.1 separates the models clearly.** Opus 5.5 usually solves it; Opus 4.7
  doesn't come close within the budget.
- **v2.1 is not a frontier-breaking task.** Opus 5.5 solves it in about 30
  minutes. But unlike v1 (12 minutes, from recall of git's source), it gets
  there by experimenting: every Opus 5.5 transcript probes the tool, forms
  hypotheses, and fuzzes against it.
- **The most informative failures are about process, not knowledge.** Before
  the clue file, all 4 Opus 5.5 runs missed `;` comments by concluding "no
  comments" once `#` was ruled out. One run ended with broken code because it
  was waiting on a long experiment when time ran out. Opus 4.7 runs missed
  braces and the depth limit and ran out of budget.
- **Small samples.** 4 valid Opus 5.5 runs and 2 valid Opus 4.7 runs. Enough
  for a direction, not a precise rate.

## v2.2: rules that don't depend on the path (folder `v22/`)

**Why.** In v2.1, Opus 5.5 solved 3 of 4 valid runs in ~30 minutes. Every
Opus 5.5 transcript discovered rules by varying paths and `.packignore`
patterns; none varied anything else about a file. v2.2 targets that.

**New hidden rules** (on top of all v2.1 rules):

| # | Truth | Evidence in the environment |
|---|---|---|
| H5 | A file whose **first line contains `@generated`** is excluded by default (when no pattern matches it; `!` re-includes it) | `snapshot/_build_info.py` starts with `# @generated by tools/release.sh`, and `tools/release.sh` writes that header. Running `tools/packignore` on the repo itself excludes `_build_info.py` though no pattern matches it |
| H6 | A file with the **executable bit** is excluded by default (same override) | `tools/packignore` and `tools/release.sh` are executable; the tool excludes both when run on the repo |

**Black box stays opaque.** The client now uploads the tree as a tar archive
(contents + permissions), a generic way to ship a directory, so its code
doesn't reveal which file properties matter. The server extracts it safely
(regular files and directories only; no absolute paths, `..`, or links) with
the same size limits.

**Grader checks**

| Check | Result |
|---|---|
| Reference tests | 19/19 (13 old + 6 new, including "only the first line counts" and "directories are never excluded for their permission bits") |
| Reference as candidate (hidden, 800 = 100 per bucket × 8) | 100% |
| README-only baseline | 17.9% (H5 1%, H6 1%) |
| One rule switched off | fails its own bucket (0%); H2's bucket drops to 70–90% when H5/H6 are off (H2 cases are rare and some also involve H5/H6) |
| Opus 5.5's perfect v2.1 solutions, scored on v2.2 | 67.5% (H5 0%, H6 0%) |
| Untouched starter, oracle down | 0% |
| Client on the starter repo (host and Docker) | excludes `snapshot/_build_info.py`, `tools/packignore`, `tools/release.sh`; README-only predicts nothing |

Run with `python3 runner/run_attempt.py --label X --task v2.2 --sandbox docker`.

**v2.2 partial runs (v22-o55-*, 12:52–13:07, stopped at 15 min because the
laptop had to close; not valid results).** Scored on their code at the stop:
591/800, 591/800, 540/800. Two of three had already implemented both H5
(generated) and H6 (executable) at 100% within 15 minutes; the third had
neither yet. Early signal: the new rules' evidence is easy for Opus 5.5 to
spot, so v2.2 may not be much harder for it. Needs full runs to confirm.

**v2.2 results (v22b-*, 2026-10-06 13:22–14:23, 60 min / $10 limits)**

| Run | Model | Score | Solved | End | Notes |
|---|---|---|---|---|---|
| v22b-o55-2 | Opus 5.5 | **800/800** | **yes** | 60 min (limit) | reached 100% at minute 51 |
| v22b-o55-1 | Opus 5.5 | 414/800 (51.8%) | no | 60 min (limit) | missed H4, H5, H6; last code change at minute 49 |
| v22b-o55-3 | Opus 5.5 | 414/800 (51.8%) | no | 15.6 min (stopped itself) | missed H4, H5, H6; reported "identical output on ~7,000 random trees" |

**Two independent runs, one model of the tool.** v22b-o55-1 and v22b-o55-3
wrote different code (220 vs 150 lines) that gives identical answers on all
800 hidden cases: both converged on the same incomplete theory, missing
braces, generated files and executables.

**Score over time** (`runner/score_over_time.py`: replays the agent's
Write/Edit calls on `ignore.py` from the transcript and scores each version;
trusted only when the rebuilt final file matches the real one):

| Minute | v22b-o55-2 | Rules still weak |
|---|---|---|
| 8 | 73.9% | H2, H4 (H5 and H6 already found) |
| 37 | 84.6% | H4 |
| 51 | **100%** | none |

Runs 1 and 3 edited partly through inline Python scripts, so their curves
can't be replayed faithfully; their last code changes were at minutes 49 and
15, with run 1 moving from about 45% (minute 8) to 51.8% without touching
the missing rules.

**Is the 60-minute limit binding?** For the success, yes: it needed 51
minutes, and a 45-minute limit would have failed it. For the failures,
probably not: one stopped itself at 15 minutes; the other spent its hour
refining a theory missing three rules. Report results as "within 60 minutes
and $10."

**Across versions (Opus 5.5, valid runs):** v1 3/3 solved (recall of git's
source), v2.1 3/4, **v2.2 1/3**.

## v2.2: all six valid Opus 5.5 runs (2026-10-06/07, 60 min / $10)

| Run | Score | Solved | Ended | Generated/executable rules (H5/H6) | Braces (H4) | What happened |
|---|---|---|---|---|---|---|
| v22b-o55-2 | **100%** | yes | 60 min (limit) | found by min 8 | found | reached 100% at min 51 |
| v22d-o55-3 | **100%** | yes | 26 min | found | found | |
| v22d-o55-2 | 84.6% | no | 60 min (limit) | found | **missed** | still changing code at min 55; at min 59 starting a new sweep for hidden directives |
| v22d-o55-1 | 67.5% | no | 53 min (stopped itself) | **missed** | found | read `_build_info.py` in min 1, never followed up; last code change min 35; reported "9,000 random trees" matched |
| v22b-o55-1 | 51.8% | no | 60 min (limit) | **found at min 59**, no time to implement | missed | tested `@generated` and executable files directly and saw both rules confirmed, one minute before the limit |
| v22b-o55-3 | 51.8% | no | 15.6 min (stopped itself) | missed | missed | reported "~7,000 random trees" matched |

**Opus 5.5 solves v2.2 in 2 of 6 runs within 60 minutes.**

**Correction to the earlier time analysis.** I first said the 60-minute limit
"probably" didn't matter for v22b-o55-1. Wrong: it discovered H5 and H6 at
minute 59 and ran out of time before implementing them. Across the six runs:
- **Time-limited (3):** v22b-o55-1 (found the rules at min 59), v22d-o55-2
  (still searching at min 59), v22b-o55-2 (solved, but only at min 51).
- **Stopped too early, confident (2):** v22b-o55-3 (min 15) and v22d-o55-1
  (min 53), each citing thousands of random trees that matched.
- **Solved comfortably (1):** v22d-o55-3 (min 26).

So the 60-minute limit is binding for half the runs, and **2-hour runs would
now add information**: they'd show how many of the time-limited runs convert,
separating "can't find it" from "can't find it in an hour."

**The evidence was always seen.** All six runs read `_build_info.py` and
`tools/release.sh` in their first minute. The differences were in whether they
followed up, and when.

**Grader/harness QA from these runs**

| # | Issue | Fix |
|---|---|---|
| 7 | The client uploaded a hard-linked file's second copy as a tar link entry; the server rejected it as unsupported, so the tool failed on trees with hard links. No hidden case has hard links (no score affected), but v22b-o55-1 spent part of its final minute on it | Client always sends regular-file entries (mode preserved); verified on a hard-linked tree |

## v2.2, 2-hour runs (v22-2h-*, 2026-10-07 10:54–12:51, 120 min / $20)

| Run | Score | Solved | Notes |
|---|---|---|---|
| v22-2h-o55-1 | **100%** | yes | finished on its own at 32 min ($5.21) |
| v22-2h-o55-2 | n/a | **invalid** | lost: the Mac restarted at 12:51 (~117 min in), killing the runner; macOS wiped the temp workspace. By min 47 it was building a Unicode character-table module, convinced behavior depended on the Unicode version |
| v22-2h-o55-3 | n/a | **invalid** | lost the same way. At min 42–47 it reported the service had slowed badly ("100 files took 26 s") and blamed its own "brace-bomb" requests |

**Why the lost runs can't be recovered.** Both edited `ignore.py` partly
through inline scripts (5 and 6 times), and one split code into a second
module, so replaying their Write/Edit calls can't rebuild their final code,
and there's no real final file left to check a rebuild against.

**The "brace bomb" was a false alarm.** Replaying every probe from that
agent's limit-testing script against the reference: all finish in ≤ 0.01 s.
The slowdown wasn't the oracle choking on a pathological pattern. A likelier
cause is host CPU contention: three agents fuzzing heavily in parallel, and
macOS flagged the Docker VM for excessive CPU at 11:02. Cause of the restart
unknown (no panic report). Mitigation for future long runs: run at most two in
parallel, or run in the cloud.

**Opus 5.5 on v2.2, all valid runs so far:** 60-min limit 2/6 solved; 2-hour
limit 1/1 solved (two more lost to the restart).

**2-hour reruns (v22-2h2-*, 2026-10-07 15:12–15:59, two at a time, on AC power)**

| Run | Score | Solved | Ended | Missed |
|---|---|---|---|---|
| v22-2h2-o55-1 | **100%** | yes | 33 min ($2.66) | nothing |
| v22-2h2-o55-2 | 87.4% | no | 45 min, stopped itself with 75 min left ($4.80) | H2 depth limit (0%); reported "zero differences" on ~4,500 random trees |

## v2.2 summary: Opus 5.5, all valid runs

| Limit | Runs | Solved | Solve times | How failures ended |
|---|---|---|---|---|
| 60 min / $10 | 6 | 2 | 26, 51 min | 2 out of time while still finding rules; 2 stopped early and confident |
| 120 min / $20 | 3 | 2 | 32, 33 min | 1 stopped early and confident at 45 min |
| **All** | **9** | **4** | 26–51 min | |

**What the extra hour showed.** All 2-hour solves finished in about 33
minutes, inside the old 60-minute limit. The one 2-hour failure stopped itself
with 75 minutes left. So a longer limit helps runs that are still actively
searching (two such runs at 60 minutes), but it doesn't help a run that
believes it's done, and that "confident and wrong" ending is the most common
way Opus 5.5 fails v2.2 (3 of 5 failures).

**Every failing run's own testing reported a perfect match:** ~7,000,
~9,000 and ~4,500 random trees "identical" in three of them. Each missed rule
(braces, generated/executable files, the depth limit) was one its random
trees never exercised.
