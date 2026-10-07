# Understanding the gitignore task, from the ground up

This is the "why" document. It explains what we are building, why each piece
exists, and how to read the results. It is meant to be read top to bottom
once, then used as a reference. The short "how to run it" lives in
`README.md`.

**Status (2026-10-05):** the grader is built and validated against three
baselines (Day 1). The starter repo and prompt are built (Day 2, Part 9). No
agent has attempted the task yet (Day 3).

**Update (2026-10-05 evening):** run 1 is done. Opus 4.7 scored 100%, and so did
its *first draft*. The task is too easy as built. See Part 10. After a
harder case set: Opus 4.7 fails 4/4 runs (83–91%), Opus 5.5 solves it. See
Part 11.

---

## Part 1: The big picture

### 1.1 What is an "RL task" for a coding agent?

AI labs improve coding agents with reinforcement learning (RL). Very roughly:

1. Give the agent a problem inside a sandbox (a repo, a terminal, tools).
2. Let it work: read files, write code, run commands.
3. Automatically score the result: a number between 0 and 1, the **reward**.
4. Nudge the model toward behavior that earned high reward.

Step 3 is the whole game. The model learns *whatever the score rewards*, not
what you meant. If the score can be earned by a shortcut, the model learns
the shortcut. This is **Goodhart's law**: "when a measure becomes a target, it
ceases to be a good measure." (Your project folder is named after it for
exactly this reason.)

A **task** is the packaged unit: a prompt, an environment, and a grader. Labs
need many of them, each hard enough that current models often fail and graded
well enough that the score means something. Companies like Mechanize build
these for a living.

### 1.2 The five parts of a task

| Part | What it is | In our task |
|---|---|---|
| **Prompt** | What the agent is told to do | "Reimplement gitignore matching in pure Python, behavior identical to git" |
| **Environment** | The sandbox the agent works in | `starter/`: a small Python tool whose `ignore.py` currently calls git |
| **Grader** | Code that turns the agent's work into a score | Compare its answers with real git on 500 hidden random cases (**built**) |
| **QA** | Proving the grader is correct and fair | Baselines, self-checks, isolation, the fairness checklist in Part 5 |
| **Failure analysis** | Showing *why* agents fail, from many transcripts | Day 3 onward |

Most people think the prompt is the hard part. It isn't. The grader and its
QA are where nearly all the effort goes, because a grader bug silently
teaches the model the wrong thing.

### 1.3 Two kinds of failure

When an agent fails your task, there are two very different explanations:

- **Model fault:** the task was fair and the agent got it wrong. This is
  what you *want*. It is a real gap that training can close.
- **Grader fault:** the agent's work was reasonable, but the grader rejected
  it. Examples: the grader checks something the prompt never mentioned, or
  the "right answer" depends on the grader's machine. This is a bug in *your*
  task, and training on it teaches the model nonsense.

Your verifier-audit project (`../verifier-audit/WRITEUP.md`) is entirely about
catching grader faults. This task is the other side: building a grader where
grader faults are as close to impossible as we can make them.

---

## Part 2: The task we chose, and why

### 2.1 The task in one paragraph

A small Python tool needs to know which files in a directory to skip, using
`.gitignore` rules. Today it shells out to `git`. Git won't exist where the
tool is deployed, so the agent must write a pure-Python function that returns
**exactly** the files git would ignore. "Exactly" is the key word: we score
it by comparing against real git on hundreds of random cases.

### 2.2 Why this particular task

We picked it against four criteria:

1. **Deterministic grading.** Same code, same score, every run. Our grader
   never uses an LLM to judge. It compares sets of file paths. ✅
2. **Fairness by construction.** The spec is "do what git does," and the
   expected answers *come from git*. We never write an expected answer by
   hand, so we can't encode our own misunderstanding of gitignore. ✅
3. **Genuinely hard.** gitignore looks simple ("`*.log` ignores log files")
   but has a long tail of rules most people, and most models, get wrong. Part
   3 walks through them. A popular library still misses ~5% of our cases. ✅
4. **Tests a behavior, not just knowledge.** Git *is available while the agent
   works* (just not in the final deployment). A careful agent will compare its
   implementation against git as it goes, which is exactly the self-checking
   habit labs want. Whether agents actually do it is one of the things we'll
   measure. ✅

This style of task has a name: **differential testing** (comparing two
implementations of the same spec on many inputs). It's how compilers,
databases, and parsers get tested in industry.

### 2.3 The backup plan

If agents ace this task, we make it harder (Part 7) or switch to PEP 440
version specifiers, which can be graded the same way against the `packaging`
library.

---

## Part 3: How gitignore actually works

You need to understand these rules to read failure reports. Each one is a
place where an implementation can go wrong.

**Basics**
- One pattern per line. Blank lines do nothing. Lines starting with `#` are
  comments.
- `*` matches anything except `/`. `?` matches one character except `/`.
  `[abc]` matches one of the listed characters, `[a-z]` a range, `[!x]` anything
  but `x`.
- **Last matching pattern wins.** Order matters.

**Where a pattern can match**
- **No slash in the pattern** (`debug.log`, `*.o`): matches a name at *any*
  depth below the `.gitignore` that contains it.
- **A slash at the start or in the middle** (`/build`, `src/main.py`): the
  pattern is *anchored* to the directory containing the `.gitignore`.
  `/build` only matches `build` at that top level, not `src/build`.
- **A slash at the end** (`build/`): matches only *directories* named `build`,
  never a file named `build`.
- `**` handles depth: `**/foo` means "foo at any depth", `foo/**` means
  "everything inside foo", `a/**/b` means "b anywhere under a".

**Negation, and the rule that trips everyone up**
- `!pattern` *un*-ignores something that an earlier pattern ignored.
- **But you can't un-ignore a file if its parent directory is ignored.** Git
  never even looks inside an ignored directory, so a `!` rule for a file in
  there never gets a chance to apply. `build/` followed by `!build/keep.txt`
  still ignores `build/keep.txt`.
- That is why `dir/**` and `dir/` behave differently. `dir/**` ignores the
  *contents* but not the directory itself, so a later `!dir/keep.txt` *does*
  work.

**Nested `.gitignore` files**
- Every directory can have its own `.gitignore`. Its patterns are relative to
  *that* directory.
- Deeper files take precedence over shallower ones.
- A `.gitignore` *inside an ignored directory is never read.*

**Escaping and whitespace**
- To match a file literally named `#notes.txt` or `!important.txt`, write
  `\#notes.txt` / `\!important.txt`. Unescaped, the first is a comment and the
  second is a negation of `important.txt`.
- `f[1].txt` as a pattern matches `f1.txt` (it's a character class!). To
  match the literal name you need `f\[1].txt`.
- Trailing spaces are stripped unless escaped with a backslash.

**Case sensitivity:** with `core.ignorecase=false`, `*.LOG` does not match
`debug.log`. Our grader fixes this setting (Part 4.2 explains why).

Our random cases exercise every rule above. The generator deliberately puts
`#notes.txt`, `!important.txt` and `f[1].txt` into file trees for this reason.

---

## Part 4: The grader, piece by piece

```
generate.py ──► random case (file tree + .gitignore files)
                     │
oracle.py ─────► ask real git which files are ignored ──► expected answer
                     │
build_cases.py ► freeze 500 cases + answers into cases/dev.jsonl
                     │
score.py ──────► write each case to disk, run the candidate in a
                 subprocess, compare its answer with the frozen answer
```

### 4.1 `generate.py`: deciding what to test

Builds a random tree (up to 4 levels deep) from a fixed list of directory
and file names, then writes 1 to 6 random lines into the root `.gitignore`
and into ~30% of the subdirectories.

Key design choices:
- **Patterns are built from names that exist in the tree.** Purely random
  patterns would almost never match anything, and every case would be
  "nothing is ignored".
- **Then they're mutated** with each rule from Part 3: globs (`*`, `?`,
  `[..]`), anchoring (`/`), `**`, trailing `/`, negation, escapes, trailing
  spaces, upper-case versions to test case sensitivity, and missing trailing
  newlines.
- **The generator never decides the answer.** It only decides what to try.
  This separation is what makes the grader trustworthy.
- **Seeded.** Case `dev-0042` is generated from the seed string `"dev-0042"`,
  so anyone can regenerate it exactly.

### 4.2 `oracle.py`: getting the truth from git

For each case: write the files to a temp directory, `git init`, then ask git
two questions:

- `git ls-files --others --ignored --exclude-standard`: which files are
  ignored?
- `git ls-files --others --exclude-standard`: which files are *not* ignored?

**Isolation.** Git's answer can be affected by things outside the case. Each
of these would be a grader fault, because the expected answer would depend on
something the agent can't see:

| Leak | What it would do | How we block it |
|---|---|---|
| Your global ignore file (`~/.config/git/ignore`) | Adds your personal patterns to every case | Fake `HOME`, `core.excludesFile=/dev/null`, no global/system config |
| `core.ignorecase=true` (git's default on macOS) | `*.LOG` would match `debug.log` on your Mac but not on Linux | Force `core.ignorecase=false` |
| Repo templates | Could add an `info/exclude` file with extra patterns | `git init --template=` (empty) |
| Case-insensitive macOS filesystem | Files `a` and `A` would collide on disk | Generator never uses names that differ only by case |

**The self-check.** Git's two answers (ignored and not ignored) must split
the file list exactly: no file in both lists, and no file in neither. If they
don't, the oracle refuses to produce an answer and crashes the build. This
catches surprises like git listing a *directory* instead of the files inside
it. In 1,000 cases it has never fired, but it's the kind of check that costs
nothing and turns a silent grader bug into a loud one.

### 4.3 `build_cases.py`: freezing the answers

Runs the generator plus the oracle 500 times and writes everything,
including git's answer, to `cases/dev.jsonl` (plus a `.meta.json` recording
the git version).

**Why freeze?** After the build, scoring never calls git. Every run on every
machine compares against the same frozen answers. If git ever changes its
behavior in a future version, our scores don't silently drift.

**Two sets.** `dev.jsonl` (seed `dev`) is for us to look at and develop
against. `hidden.jsonl` (seed `hidden`) is the real exam. The agent must
never see it, otherwise it could tune its code to the specific cases instead
of implementing gitignore correctly. That's the train/test split from ML,
applied to a grader.

### 4.4 `score.py` + `run_candidate.py`: scoring an implementation

**The contract** the agent's code must meet:

```python
def ignored_files(root: str) -> list[str]:
    """root holds the files and .gitignore files of one case (no .git dir).
    Return the POSIX paths, relative to root, of every FILE git would ignore.
    Do not list directories."""
```

The scorer writes each case to disk, runs the candidate **in a separate
process** (so a crash or infinite loop can't take down the grader), and
compares sets.

**Scoring rule:** a case passes only if the candidate's set equals git's
set *exactly*. The headline score is the fraction of cases passed. File-level
accuracy is reported too, but only as a diagnostic. Why so strict? A tool
that is "99% right about which files to skip" will still back up your
`.env` or skip your source code now and then, and the prompt promises
identical behavior. It also keeps the number meaningful: file-level accuracy
is inflated by the many files that are trivially not ignored.

**No git at scoring time.** Candidates run with an empty `PATH`, so code that
just calls `git` fails. This enforces the task's premise. The `--allow-git`
flag exists only for the plumbing check below.

**Per-feature breakdown:** for each rule (negation, `**`, escapes...), the
pass rate on cases that contain that rule. Known weakness: most cases contain
many rules at once, so this table is blunt for now (see Part 6).

---

## Part 5: How we know the grader works

A grader is code, and code has bugs. Before any agent touches the task, we
test the grader with **baselines**: implementations whose scores we can
predict. If a baseline scores unexpectedly, the grader is wrong, not the
baseline.

### 5.1 The three baselines

| Baseline | What it does | Expected | Got (dev, 500 cases) | What it proves |
|---|---|---|---|---|
| `git_wrapper.py` | Just calls git (with `--allow-git`) | 100% | **100.0%** | The plumbing (writing files, paths, comparison) is correct. It can't be wrong about git, so any failure would be a scorer bug. |
| `git_wrapper.py` | Same, default settings | 0% | **0.0%** (500 errors) | The "no git at scoring time" rule actually bites. |
| `naive_fnmatch.py` | Pools all patterns, ignores directories and anchoring, uses Python's `fnmatch` | Low | **22.2%** | The cases aren't trivial; a quick first attempt fails most of them. |
| `pathspec_nested.py` | The popular `pathspec` library, wired up with git's directory-walking rules | High but not perfect | **94.6%** | The task is solvable, but even a mature library misses real edge cases. |

### 5.2 What the pathspec misses teach us

The 27 cases pathspec fails are real disagreements between pathspec and git.
For example, in case `dev-0057` the root `.gitignore` says:

```
out/**
!/*
```

`out/**` ignores everything inside `out/`. `!/*` un-ignores entries *at the
top level only*. So git still ignores `out/main.py`, but pathspec treats `!/*`
as also matching things inside `out/` and un-ignores it.

This is the kind of mistake we expect agents to make too. Many will reach for
pathspec-style logic from memory. That's good news for the task's difficulty,
and each such disagreement becomes a line in the failure analysis.

**Caveat:** the pathspec baseline includes our own wiring code (the
directory walk). Some of its misses could be our wiring bugs rather than
pathspec bugs. That doesn't matter for its purpose here, which is to show the
task has real traps, but we shouldn't claim "pathspec is wrong about X"
publicly without checking each case.

### 5.3 The fairness checklist

Every check the grader makes should be knowable by the agent. Going through
it:

- [x] **Is the expected answer derivable from the spec?** Yes: the spec is
  "match git", and the answer comes from git.
- [x] **Is the answer independent of the grader's machine?** Yes, after the
  isolation in Part 4.2. Answers are frozen with the git version recorded.
- [x] **Does the prompt state the output contract exactly?** Files only,
  sorted, relative, `/` separators, same function signature. Stated in
  `PROMPT.md` *and* in the docstring the agent starts from.
- [x] **Does the prompt pin down configuration?** It says case-sensitive and
  no global excludes. Without this, an agent that honors `core.ignorecase`
  (reasonable on a Mac!) would be marked wrong, which would be a grader fault.
- [x] **Does the prompt say which ignore sources count?** Only `.gitignore`
  files inside `root`.
- [x] **Does the prompt say how strict "identical" is?** Yes: "checked against
  git on a large set of generated trees." Without that sentence, failing an
  agent on `!/!important.t?t` could fairly be called a gotcha.
- [ ] **Can the agent check its own work?** The prompt says git is available.
  The Day 3 runner must actually make it so.

These are exactly the "the grader checks something the prompt never
mentioned" failures that the verifier-audit write-up is about.

### 5.4 QA log so far

Grader issues found while building, before any agent ran. This becomes a
section of the public write-up.

| # | Issue | Impact if missed | Fix |
|---|---|---|---|
| 1 | git defaults to `core.ignorecase=true` on macOS | Expected answers would differ between your Mac and a Linux grader | Force `core.ignorecase=false` in the oracle |
| 2 | Global ignore file and system config leak into the oracle | Your personal ignores would become "correct answers" | Fake `HOME`, null excludes file, no global/system config |
| 3 | `git init` copies template files | A template `info/exclude` could add patterns | `--template=` (empty) |
| 4 | macOS filesystem is case-insensitive | `a` and `A` in one case would collide on disk | Name lists contain no case-only duplicates |
| 5 | Candidate could just call git | A "solution" that defeats the premise would score 100% | Candidates run with empty `PATH`; verified git_wrapper scores 0% |
| 6 | `pathspec` is installed in the system Python | Agent could import a ready-made matcher | Prompt forbids third-party packages. **Open:** Day 3 runner must also not have it installed |
| 7 | Empty `PATH` doesn't block `/usr/bin/git` | A determined agent could still call git | Prompt forbids subprocesses. **Open:** scoring should also grep the solution for `subprocess`/`os.system` and flag it |
| 8 | Scorer loaded candidates as a lone file | An agent that split code into `snapshot/_glob.py` with a relative import would crash, a grader fault | Scorer imports files inside a package by dotted name; verified on `starter/snapshot/ignore.py` |
| 10 | Docker sandbox: git refused the mounted workspace ("dubious ownership") | Agent couldn't run git in the container, so it couldn't check its work as the prompt promises: a grader fault | `safe.directory '*'` in the image; verified `git log` works inside |
| 11 | Container has git 2.47.3; hidden answers came from git 2.50.1 | If versions disagreed, an agent matching *its* git would be marked wrong | Ran the git-calling version inside the container on all 500 hidden cases: 100% agreement |
| 12 | Scorer converted `\\` to `/` in returned paths | A correct answer for a file literally named `a\b` (legal on macOS/Linux) was marked wrong: 3 of 60 pilot cases | Removed the conversion; contract already requires `/`-separated paths. Found while checking the first hard-profile failures |
| 9 | "Do nothing" must not score | If the untouched starter scored anything, the reward would be free | Untouched starter scores 0% (git blocked) and 100% with `--allow-git` |

---

## Part 6: Known weaknesses and open questions

Being honest about these is part of the work.

1. **Is it hard enough?** pathspec gets 94.6%. A frontier agent that knows
   gitignore well, and checks itself against git, might reach 95–100%. We won't
   know until Day 3. If agents pass ~80%+ of runs, we make it harder.
2. **Random cases aren't realistic.** Real `.gitignore` files look like
   `node_modules/`, `*.pyc`, `.env`, not `!/!important.t?t`. An agent could fail
   on bizarre cases nobody writes in practice. Defense: the prompt says
   "identical to git", and git defines behavior for every input. Still, a
   fair critique is "this tests trivia." A possible fix is a second case set
   built from real-world `.gitignore` files (e.g. GitHub's templates).
3. **The feature table is blunt.** Most cases contain 8+ features, so a
   feature's pass rate mostly reflects overall difficulty. Fix later: report
   for each failing case the *single* feature responsible (by deleting lines
   until the case passes, a technique called "delta debugging").
4. **Exact-match scoring is harsh.** One wrong file fails the whole case.
   That's deliberate (Part 4.4), but it means scores can jump around. We'll
   check run-to-run variance on Day 3.
5. **Memorization.** An agent might reproduce pathspec's source from memory.
   That would still only reach ~95%, so the task stays discriminating. But it's
   worth noticing in transcripts.
6. **Unicode, CRLF line endings, symlinks, and filenames with spaces** are
   not generated yet. Each is a real gitignore edge case. Add them if the task
   turns out too easy.

---

## Part 7: How we'd make it harder if needed

In order of preference:
1. **Hide the target.** Don't name `.gitignore` semantics up front; make the
   agent discover that the tool's behavior *is* git's from the code.
2. **Add the remaining edge cases** from Part 6.6.
3. **Add sources:** `.git/info/exclude` and `core.excludesFile` precedence.
4. **Raise the bar:** require 100% on hidden cases for any reward (binary
   reward), which makes "pretty good" worth nothing.
5. **Embed it in a bigger repo** where the matcher has to fit existing code
   conventions. That combines this task with idea B.

---

## Part 8: What happens next

**Day 3: first agent runs**
- Write a runner: copy `starter/` into a fresh temp folder, make it a git repo
  with one commit (so `git show HEAD:snapshot/ignore.py` recovers the
  original), check `pathspec` isn't importable, start Claude Code with
  `PROMPT.md`, save the transcript.
- Run it ~5 times. Score each attempt's `snapshot/ignore.py` on the hidden set.
- Read the transcripts: did the agent test against git? Where did it stop?
- Decide: keep, make harder, or switch to the backup.

---

## Part 9: The agent's side (Day 2)

### 9.1 The starter repo (`starter/`)

`snapshot` is a tiny tool: `python3 -m snapshot SRC DEST` copies a project
and skips ignored files.

| File | Role |
|---|---|
| `snapshot/ignore.py` | `ignored_files(root)`, currently implemented by calling git. **This is what the agent rewrites.** Its docstring states the output contract. |
| `snapshot/cli.py` | Uses `ignored_files` to do the copy. Gives the task a real reason to exist. |
| `tests/test_ignore.py` | 10 easy visible tests: `*.log`, `build/`, negation, comments, `/anchored`, a nested `.gitignore`, path format. |
| `tests/test_cli.py` | 1 end-to-end test of the copy. |

**Why a real tool instead of a bare function?** Real work is "replace this
dependency in this codebase," not "implement gitignore from scratch." The
agent has to read the existing code to learn the contract, which is closer to
the job and to how a lab would want the task to look.

**Why the visible tests are easy on purpose.** They catch format mistakes,
so an agent can't fail on a technicality without noticing. But they cover none
of the hard rules from Part 3. They're the bait: an agent that runs them, sees
11/11 green, and stops will fail the hidden set. An agent that keeps testing
against git won't. That gap between the two is what the task measures.

**What the agent does not see:** `grader/`, `cases/`, `baselines/` (pathspec
wiring would be a hint), this document, and the 500 dev cases. We decided not
to hand over the dev cases: with git available, generating its own test cases
*is* the skill being tested.

### 9.2 The prompt (`PROMPT.md`)

Each sentence has a job:

| Sentence | Why it's there |
|---|---|
| "deploying to machines where git isn't installed" | A realistic reason. Also explains why calling git is off the table. |
| "exactly what the current git-based version returns" | The spec is the existing code's behavior, which is git's behavior. No ambiguity to argue about. |
| "Standard library only... no subprocesses" | Closes two reward hacks: importing pathspec, calling git. Stated up front, so a failure on it is the agent's fault. |
| "sorted list of file paths... Files only" | The output contract, so a correct matcher can't fail on format. |
| "only `.gitignore` files inside `root`... case-sensitive" | Pins the configuration (QA log #1 and #2, from the agent's side). |
| "checked against git on a large set of generated trees" | Tells the agent how strict "exactly" is. Makes unusual-pattern failures fair. |
| "tests are not exhaustive" | Fair warning that green tests aren't the finish line. |
| "Git is installed while you work" | Invites self-checking without telling the agent *how* to do it. |

**What the prompt deliberately does not say:** it doesn't list the tricky
rules (negation inside ignored directories, escapes, `**`). Listing them would
turn a test of thoroughness into a checklist. This is a judgment call: one
could argue it makes the task harder than necessary. The defense is that the
prompt gives the agent everything needed to *discover* them (the spec, the
strictness, and git itself).

### 9.3 Verified

| Check | Result |
|---|---|
| Visible tests pass on the original git version | 11/11 |
| Untouched starter, scored with git blocked | 0% (doing nothing earns nothing) |
| Untouched starter, scored with `--allow-git` | 100% (the starter's contract matches the grader's) |

---

## Part 10: Run 1 results (Opus 4.7, local sandbox)

| | |
|---|---|
| Hidden score | **500/500 (100%)**, also 500/500 on dev |
| Rule checks | No banned imports or subprocesses (`os` and `re` only); visible tests pass; no contamination |
| Time | Hit the 60-minute cap while still testing; the solution was already complete |
| Cost | Not recorded: the runner only reads cost from the final event, which a timeout never emits. Fix pending. |
| Solution | 241 lines |

**What the agent did.** Read the code, wrote a full 244-line matcher in one go,
ran the visible tests, then wrote its *own* git-comparison fuzzer, ran
thousands of cases, found a real edge case (`bc**/a` matches `bca`: git treats
`**/` as "zero or more directories" even when glued to other characters),
checked it against git directly, fixed it, and kept widening its fuzzer until
the cap.

**The key finding: its first draft, before any self-testing, already scored
100% on our hidden set.** So:

1. **Opus 4.7 knows gitignore very well.** The rules in Part 3 that we expected
   to trip it up (negation inside ignored directories, escapes, anchoring) it
   got right from memory.
2. **Our case generator is weaker than the agent's fuzzer.** The agent found
   `bc**/a` style cases; our 1,000 cases contain none that its first draft got
   wrong. Our grader can't tell a good-from-memory implementation from a
   thoroughly tested one, so the "did it self-check" behavior we wanted to
   reward currently earns nothing extra.
3. **pathspec at ~94% was a misleading difficulty signal.** It measured a
   library's quirks (and our wiring), not what a frontier model would get wrong.

This is the "first ideas are too easy" outcome. It's a useful result, not a
failure: it took one run to find out, and the transcript shows *why*.

**Possible next moves** (see Part 7):
- **Strengthen the generator** with the kinds of patterns the agent's own
  fuzzer found (`**` glued to text, `x**`, odd escapes, deeper trees), then
  rescore this run's first draft. If the draft drops below 100%, the grader
  can now reward self-testing.
- **Remove the easy self-check:** no git in the work sandbox. The agent must
  implement from knowledge and the docs alone. Harder and more realistic for
  "port a dependency" work, but the prompt must still make "identical to git"
  fair.
- **Switch targets** to something models know less well than gitignore
  (PEP 440 specifiers, or a less famous format).

### 10.1 Strengthening the grader (option 1)

Added a **hard profile** to the generator (`gen_case_hard`), modeled on the
agent's own fuzzer: tiny alphabet names so patterns collide, trees up to 5
deep, odd filenames (`a b`, `a*`, `[a]`, `a\b`), and syntax neither
generator covered: glued and repeated `**`, POSIX classes, `[]a]`, `[^a]`,
reversed ranges, escapes of ordinary letters, leading spaces, trailing tabs,
CRLF. Rare forms are picked less often so one quirk can't dominate. Built
`cases/hard-dev.jsonl` (300) and `cases/hard-hidden.jsonl` (500).

| Candidate | Original hidden | **Hard hidden** |
|---|---|---|
| git wrapper (`--allow-git`) | 100% | **100%** |
| Run 1 first draft | 100% | **90.0%** |
| Run 1 final | 100% | **90.2%** |
| pathspec + wiring | 93.8% | 47.4% |
| naive fnmatch | 23.2% | 25.6% |

### 10.2 Why run 1 fails the hard set: three bugs

`grader/minimize.py` shrinks each failing case by deleting `.gitignore` lines
while the candidate still disagrees with git. Every one of run 1's 49 hard-set
failures reduces to one of three root causes:

| Bug | Cases | Minimal example | What git does | What the agent does |
|---|---|---|---|---|
| **No POSIX classes** | 14 | `[[:alpha:]]` | Matches any one letter (git's wildmatch supports `[:alpha:]`, `[:digit:]`, ...) | Treats it as a broken bracket expression; ignores nothing |
| **Runs of 3+ stars** | 7 | `***/aaa` | Treats `***/` like `**/`: zero or more directories | Treats it as a single-level `*` and misses deeper matches |
| **Reversed range crashes** | 28 | `[b-a]` | Accepts it; matches nothing | Passes it to Python's `re`, which raises `bad character range` |

**What this says about the agent.** It did build a git-comparison fuzzer and
ran thousands of cases, and found a real quirk (`bc**/a`). But its fuzzer's
vocabulary had no POSIX classes, no runs of 3+ stars, and no reversed ranges,
so it never tested them, and it then reported the work as done. The failure
isn't "didn't test"; it's "tested only what it already thought of." Its fuzz
coverage mirrored its own mental model, so it couldn't find the gaps in that
model. That's a crisp, model-side failure, and the kind Mechanize asks for.

**Is it fair?** Each behavior is git's documented or observable behavior on a
valid input, the prompt says "identical on every input, including unusual
patterns", and git was available to check. POSIX classes in particular are
documented (gitignore defers to fnmatch/wildmatch). A reasonable critique
remains that `***/aaa` and `[b-a]` are inputs nobody writes on purpose.

### 10.3 Proposed scoring

Score each attempt on **both** hidden sets (1,000 cases) and report them
separately, plus a strict **solved** flag (zero disagreements on all 1,000).
Run 1: 100% / 90.2% / not solved. The headline reward would be the combined
pass rate (95.1% for run 1); the "solved" rate across runs is the number for
the write-up.

## Part 11: Five runs, two models (Docker sandbox)

After the hard set was added, four more attempts ran in parallel, each in its
own Docker container (`--sandbox docker`), scored on both hidden sets.

| Run | Model | Original | **Hard** | Solved | Time | Cost (est.) |
|---|---|---|---|---|---|---|
| run 1 | Opus 4.7 | 100% | 90.2% | no | 60 min (time cap) | n/a |
| d1 | Opus 4.7 | 100% | 90.8% | no | 32 min (budget cap) | $10.08 |
| d2 | Opus 4.7 | 100% | 83.4% | no | 12 min | $3.17 |
| d3 | Opus 4.7 | 100% | 85.0% | no | 32 min | $9.93 |
| o55-1 | Opus 5.5 | 100% | **100%** | **yes** | 11 min | $1.50 |
| o55-2 | Opus 5.5 | 100% | **100%** | **yes** | 12 min | $2.12 |
| o55-3 | Opus 5.5 | 100% | **100%** | **yes** | 13 min | $1.45 |

(run 1 used the local sandbox and the 1M-context variant; the others used
Docker and the standard variant.)

### 11.1 Failure analysis: Opus 4.7

Every wrong answer minimized (`grader/minimize.py`) and grouped by root cause.
Numbers are hard-set cases lost to each bug.

| Bug (minimal example) | run 1 | d1 | d2 | d3 | Runs |
|---|---|---|---|---|---|
| Reversed range crashes the regex compiler (`[b-a]`) | 28 | 28 | 28 | 26 | **4/4** |
| POSIX classes unsupported (`[[:alpha:]]`) | 14 | 14 | 12 | 12 | **4/4** |
| Trailing tab stripped (git strips only spaces) (`**/ \t`) | 0 | 0 | 37 | 37 | 2/4 |
| Star runs / `a**` with directory negation (`***/aaa`; `a**` + `!ab/`) | 7 | 4 | 6 | 0 | 3/4 |

**Findings:**
1. **Two blind spots are perfectly consistent** across runs and sandboxes:
   reversed ranges and POSIX classes. Every Opus 4.7 attempt has both.
2. **All 4 attempts fuzzed against git**, ran thousands of cases, and reported
   the work as matching git. None of their fuzzers generated POSIX classes or
   reversed ranges, so none could find those bugs. **Self-testing only covers
   what the tester already thinks of.**
3. **More effort didn't buy coverage.** d1 and d3 spent ~3x the time and cost
   of d2 for a few points more. d1 did find and fix run 1's star-run bug on its
   own, so the extra effort isn't useless, but it never reaches the blind spots.
4. **Opus 5.5 solved it by recall.** Its transcript describes porting git's
   `wildmatch.c` nearly line for line, including quirks our generator doesn't
   even test (BOM, NUL bytes, symlinked `.gitignore`). Fast, cheap, correct.

### 11.2 What this means for the task

- **As a frontier training task: too easy.** The newest model solves it in 11
  minutes. The root cause is structural: the spec is a famous open-source
  behavior whose reference implementation the model has memorized. Confirmed:
  Opus 5.5 solved 3/3 runs, each in ~12 minutes for ~$1.50–2.
- **The reward signal is lumpy.** The most common failure (`[b-a]`) is an
  input nobody writes on purpose and is worth ~5.6 points by itself. POSIX
  classes are the strongest, fairest finding: documented and used in real
  `.gitignore` files.
- **As a portfolio artifact it's complete:** a fair-by-construction grader,
  12 grader bugs caught in QA, a "too easy" result found and fixed with
  evidence, and a multi-run failure analysis with root causes.

**v2 is built:** see `V2_DESIGN.md` for the rules, layout, grader checks and
QA log. **Next idea (v2): black-box behavior cloning.** Replace gitignore with a
custom matcher whose rules are deliberately novel, shipped to the agent only
as a compiled program it can query, with no source and no docs. Memory can't
help; the agent must discover the rules by experiment. That directly removes
the weakness Opus 5.5 exposed.

---

## Glossary

- **Agent:** an AI model that takes actions (runs commands, edits files)
  in a loop, not just answering once.
- **Baseline:** an implementation with a predictable score, used to test
  the grader.
- **Candidate:** any implementation being scored (an agent's, or a baseline).
- **Differential testing:** comparing two implementations of the same spec
  on many inputs; any disagreement is a bug in one of them.
- **Grader / verifier:** code that scores the agent's work.
- **Grader fault vs model fault:** whether a failure is the task designer's
  bug or the agent's genuine mistake.
- **Hidden set:** test cases the agent never sees, used for the real score.
- **Oracle:** the source of truth for expected answers, here real git.
- **Reward:** the score fed back into RL training.
- **Reward hacking:** the agent earning a high score without doing the
  intended thing (e.g. calling git instead of implementing the matcher).
- **Transcript:** the full log of what an agent did during one attempt.
