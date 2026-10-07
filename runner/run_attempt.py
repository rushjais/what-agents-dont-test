"""Run one Claude Code attempt at the task, then grade it.

    python3 runner/run_attempt.py --label opus-1 [--model opus] [--effort high] [--budget 10]
    python3 runner/run_attempt.py --label d1 --sandbox docker
    python3 runner/run_attempt.py --label v2-1 --task v2 --sandbox docker

--task v1: gitignore (oracle: git). --task v2: packignore, an invented tool the
agent can only query (oracle: v2/reference, served from this machine by
v2/server/oracle_server.py for the duration of the agent run).

Steps:
  1. Copy starter/ into a fresh workspace OUTSIDE this project (so the agent
     can't stumble onto grader/ or cases/), make it a git repo with one commit.
  2. Create a clean venv for the agent (no pathspec) and put it first on PATH.
     Git stays available, as the prompt promises.
  3. Run `claude -p` with PROMPT.md, saving the full stream-json transcript.
  4. Grade: static check, visible tests, hidden-set score, contamination check.
  5. Save everything to runs/<id>/.
"""

import argparse
import datetime
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

TASK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TASK)

from grader.score import score, summarize  # noqa: E402
from grader.static_check import check  # noqa: E402

ALLOWED_TOOLS = "Bash Read Edit Write Glob Grep TodoWrite"
# Explains the harness, not the task. In `claude -p` the session ends when the agent
# ends its turn, so work started in the background never reports back; one run ended
# mid-verification "waiting to be notified" (v2d-o55-1).
HARNESS_NOTE = ("You are running non-interactively: when you end your turn, the session ends "
                "and nothing you started in the background will report back. Run commands in "
                "the foreground, and finish the task before ending your turn.")
DENIED_TOOLS = "WebFetch WebSearch"
# Strings that would show the agent looked at grader-side files.
CONTAMINATION = ["Goodhart", "gitignore-task", "hidden.jsonl", "dev.jsonl", "UNDERSTANDING.md",
                 "V2_DESIGN", "oracle_server", "reference/packignore"]

TASKS = {
    "v1": {"starter": os.path.join(TASK, "starter"), "prompt": os.path.join(TASK, "PROMPT.md"),
           "cases": [os.path.join(TASK, "cases", "hidden.jsonl"),
                     os.path.join(TASK, "cases", "hard-hidden.jsonl")]},
    "v2": {"starter": os.path.join(TASK, "v2", "starter"), "prompt": os.path.join(TASK, "v2", "PROMPT.md"),
           "cases": [os.path.join(TASK, "v2", "cases", "hidden.jsonl")], "dir": "v2"},
    "v2.2": {"starter": os.path.join(TASK, "v22", "starter"), "prompt": os.path.join(TASK, "v22", "PROMPT.md"),
             "cases": [os.path.join(TASK, "v22", "cases", "hidden.jsonl")], "dir": "v22"},
}


def load_v2_scorer(task_dir):
    spec = importlib.util.spec_from_file_location("v2score", os.path.join(TASK, task_dir, "grader", "score.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start_oracle(task_dir):
    """Start the packignore oracle on a free port. Returns (process, port)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, os.path.join(TASK, task_dir, "server", "oracle_server.py"),
                             "--port", str(port)], stdout=subprocess.PIPE, text=True)
    if "oracle on" not in proc.stdout.readline():
        raise SystemExit("packignore oracle failed to start")
    return proc, port


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def setup_workspace(ws, starter):
    repo = os.path.join(ws, "repo")
    shutil.copytree(starter, repo,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    env = {**os.environ, "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
           "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}
    sh(["git", "init", "-q"], cwd=repo)
    sh(["git", "add", "-A"], cwd=repo)
    sh(["git", "commit", "-q", "-m", "snapshot: initial version"], cwd=repo, env=env)

    venv = os.path.join(ws, "venv")
    sh([sys.executable, "-m", "venv", venv])
    probe = subprocess.run([os.path.join(venv, "bin", "python"), "-c", "import pathspec"],
                           capture_output=True)
    if probe.returncode == 0:
        raise SystemExit("isolation failure: pathspec is importable in the agent venv")
    return repo, venv


def run_agent(repo, venv, transcript_path, args, prompt_path, oracle_port=None):
    prompt = open(prompt_path).read()
    cmd = ["claude", "-p", prompt,
           "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk",
           "--allowedTools", ALLOWED_TOOLS,
           "--disallowedTools", DENIED_TOOLS,
           "--strict-mcp-config",
           "--setting-sources", "project",
           "--no-session-persistence",
           "--max-budget-usd", str(args.budget),
           "--append-system-prompt", HARNESS_NOTE]
    if args.model:
        cmd += ["--model", args.model]
    if args.effort:
        cmd += ["--effort", args.effort]
    # Drop variables inherited from a parent Claude Code session (e.g. when launched
    # from inside the desktop app): they point the child at the parent's auth proxy
    # and it fails with 401. Without them it uses the normal CLI login.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE") and k not in ("ANTHROPIC_BASE_URL", "VIRTUAL_ENV")}
    container = None
    if oracle_port:
        host = "host.docker.internal" if args.sandbox == "docker" else "127.0.0.1"
        env["PACKIGNORE_URL"] = f"http://{host}:{oracle_port}"
    if args.sandbox == "docker":
        # Only the workspace is mounted. Auth comes from a long-lived token made with
        # `claude setup-token`, passed by name so it never appears in the process list.
        token = os.environ.get("AGENT_OAUTH_TOKEN")
        token_file = os.path.expanduser("~/.config/snapshot-task/oauth_token")
        if not token and os.path.exists(token_file):
            token = open(token_file).read().strip()
        if not token:
            raise SystemExit(f"--sandbox docker needs a token from `claude setup-token`, "
                             f"in {token_file} or AGENT_OAUTH_TOKEN")
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        container = "snapshot-attempt-" + os.path.basename(os.path.dirname(repo))
        docker = shutil.which("docker") or "/Applications/Docker.app/Contents/Resources/bin/docker"
        cmd = [docker, "run", "--rm", "--name", container,
               "--user", f"{os.getuid()}:{os.getgid()}",
               "--memory", "4g", "--cpus", "2",
               "-e", "CLAUDE_CODE_OAUTH_TOKEN",
               *(["-e", "PACKIGNORE_URL"] if oracle_port else []),
               "-v", f"{repo}:/work/repo", "-w", "/work/repo",
               args.image] + cmd
    else:
        env["PATH"] = os.path.join(venv, "bin") + os.pathsep + os.environ["PATH"]
    # Wall-clock deadline. subprocess's own timeout uses a clock that pauses while a
    # Mac sleeps, so an overnight sleep let runs resume hours later past their limit.
    start = time.time()
    deadline = start + args.timeout * 60
    with open(transcript_path, "w") as out, tempfile.TemporaryFile("w+") as err:
        proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=out, stderr=err, text=True)
        while proc.poll() is None and time.time() < deadline:
            time.sleep(2)
        if proc.poll() is None:
            status = "timeout"
            if container:
                subprocess.run([cmd[0], "kill", container], capture_output=True)
            proc.kill()
            proc.wait()
        else:
            status = f"exit {proc.returncode}"
        err.seek(0)
        stderr = err.read()
    return status, stderr, time.time() - start


def read_transcript(path):
    events = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    model, result, commands = None, {}, []
    per_msg = {}
    for ev in events:
        # Token usage is per assistant message; a message can span several events
        # with the same id, and early events carry partial counts, so keep the max
        # per id. This survives a timeout, unlike the final "result" event that
        # carries total_cost_usd.
        if ev.get("type") == "assistant":
            msg = ev.get("message", {})
            u = per_msg.setdefault(msg.get("id"), {})
            for k, v in (msg.get("usage") or {}).items():
                if isinstance(v, int):
                    u[k] = max(u.get(k, 0), v)
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            model = ev.get("model")
        elif ev.get("type") == "result":
            result = ev
        elif ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Bash":
                    commands.append(block["input"].get("command", ""))
    usage = {}
    for u in per_msg.values():
        for k, v in u.items():
            usage[k] = usage.get(k, 0) + v
    return model, result, commands, usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--budget", type=float, default=10.0, help="max USD for the agent run")
    ap.add_argument("--timeout", type=float, default=60, help="minutes")
    ap.add_argument("--task", choices=list(TASKS), default="v1")
    ap.add_argument("--cases", nargs="+", help="default: the task's hidden set(s)")
    ap.add_argument("--sandbox", choices=["local", "docker"], default="local",
                    help="local: agent runs on this machine in a temp dir; docker: in a container")
    ap.add_argument("--image", default="snapshot-task-agent",
                    help="docker image (build: docker build -t snapshot-task-agent runner/)")
    args = ap.parse_args()
    task = TASKS[args.task]
    args.cases = args.cases or task["cases"]

    if args.sandbox == "docker" and not (os.environ.get("AGENT_OAUTH_TOKEN") or os.path.exists(
            os.path.expanduser("~/.config/snapshot-task/oauth_token"))):
        raise SystemExit("--sandbox docker needs a token from `claude setup-token`, in "
                         "~/.config/snapshot-task/oauth_token or AGENT_OAUTH_TOKEN")

    # Keep the machine awake for the whole run (macOS). Sleep mid-run stalls the
    # agent, drops API connections and corrupts timing; two v2 runs were lost to it.
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())])

    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + args.label
    out_dir = os.path.join(TASK, "runs", run_id)
    os.makedirs(out_dir)
    ws = tempfile.mkdtemp(prefix="snapshot-attempt-")
    repo, venv = setup_workspace(ws, task["starter"])
    print(f"[{run_id}] task {args.task}, workspace {repo}", flush=True)

    oracle, port = start_oracle(task["dir"]) if args.task != "v1" else (None, None)
    transcript = os.path.join(out_dir, "transcript.jsonl")
    try:
        status, stderr, secs = run_agent(repo, venv, transcript, args, task["prompt"], port)
    finally:
        # Stop the oracle BEFORE grading: an untouched starter calls it, and must not score.
        if oracle:
            oracle.terminate()
            oracle.wait()
    print(f"[{run_id}] agent finished: {status} after {secs / 60:.1f} min", flush=True)

    # Keep the agent's final repo (and its diff) for reading later.
    shutil.copytree(repo, os.path.join(out_dir, "workspace"),
                    ignore=shutil.ignore_patterns("__pycache__", ".git"))
    diff = subprocess.run(["git", "diff", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo,
                               capture_output=True, text=True).stdout
    with open(os.path.join(out_dir, "diff.patch"), "w") as f:
        f.write(diff + ("\n# untracked files:\n" + untracked if untracked else ""))

    model, result, commands, usage = read_transcript(transcript)
    with open(os.path.join(out_dir, "commands.txt"), "w") as f:
        f.write("\n\n".join(f"$ {c}" for c in commands))

    flags = check(os.path.join(repo, "snapshot"))
    tests = None
    if os.path.isdir(os.path.join(repo, "tests")):
        tests = subprocess.run([os.path.join(venv, "bin", "python"), "-m", "unittest"], cwd=repo,
                               capture_output=True, text=True)
    v2 = load_v2_scorer(task["dir"]) if args.task != "v1" else None
    candidate = os.path.join(repo, "snapshot", "ignore.py")
    sets, all_rows = {}, []
    for path in args.cases:
        with open(path) as f:
            cases = [json.loads(line) for line in f]
        name = os.path.basename(path).removesuffix(".jsonl")
        if v2:
            rows = v2.score(candidate, cases)
            sets[name] = v2.summarize(rows)
        else:
            rows = score(candidate, cases, timeout=600)
            sets[name] = summarize(cases, rows)
        all_rows += rows
    passed = sum(r["pass"] for r in all_rows)
    hidden = {"score": passed / len(all_rows), "passed": passed, "cases": len(all_rows),
              "errors": sum(r["error"] is not None for r in all_rows)}
    raw = open(transcript).read()
    contamination = [s for s in CONTAMINATION if s in raw]

    summary = {
        "run_id": run_id,
        "model": model,
        "effort": args.effort,
        "agent_status": status,
        "minutes": round(secs / 60, 1),
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
        "token_usage_partial": usage,  # stream events undercount output; input is a usable estimate
        "agent_final_message": result.get("result"),
        "bash_commands": len(commands),
        "static_flags": flags,
        "task": args.task,
        "visible_tests_pass": None if tests is None else tests.returncode == 0,
        "hidden_score": hidden["score"],
        "hidden_passed": f"{hidden['passed']}/{hidden['cases']}",
        "hidden_errors": hidden["errors"],
        "per_set": {k: {"score": v["score"], "passed": f"{v['passed']}/{v['cases']}",
                        **({"by_rule": {r: x["rate"] for r, x in v["by_rule"].items()}}
                           if "by_rule" in v else {})}
                    for k, v in sets.items()},
        "solved": passed == len(all_rows) and not flags,
        "contamination_hits": contamination,
        "reward": 0.0 if flags else hidden["score"],
    }
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(out_dir, "hidden_report.json"), "w") as f:
        json.dump({"summary": hidden, "per_set": sets, "rows": all_rows}, f, indent=2)
    if stderr.strip():
        with open(os.path.join(out_dir, "agent_stderr.txt"), "w") as f:
            f.write(stderr)

    print(json.dumps({k: v for k, v in summary.items() if k != "agent_final_message"}, indent=2))
    shutil.rmtree(ws, ignore_errors=True)


if __name__ == "__main__":
    main()
