"""Rebuild every version of an agent's ignore.py from its transcript and score each one.

    python3 runner/score_over_time.py runs/<run_id> --task v2.2

Answers "was the agent still improving when time ran out?" without new runs.
Replays the Write/Edit tool calls on snapshot/ignore.py in order, starting
from the starter's version, and scores each distinct version on the task's
hidden set. Edits made any other way (shell redirects, sed, scripts) can't be
replayed, so the rebuilt final version is checked against the real final file;
a mismatch is reported rather than trusted.
"""

import argparse
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_attempt  # noqa: E402

TARGET = "snapshot/ignore.py"


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def versions(transcript, start_text):
    text, start, out = start_text, None, []
    for line in open(transcript):
        e = json.loads(line)
        if e.get("timestamp") and start is None:
            start = ts(e["timestamp"])
        if e.get("type") != "assistant":
            continue
        for b in e["message"].get("content", []):
            if b.get("type") != "tool_use" or b["name"] not in ("Write", "Edit", "MultiEdit"):
                continue
            inp = b["input"]
            if not str(inp.get("file_path", "")).endswith(TARGET):
                continue
            if b["name"] == "Write":
                new = inp["content"]
            else:
                new = text
                edits = inp.get("edits") or [inp]
                for ed in edits:
                    if ed["old_string"] not in new:
                        new = None
                        break
                    new = (new.replace(ed["old_string"], ed["new_string"]) if ed.get("replace_all")
                           else new.replace(ed["old_string"], ed["new_string"], 1))
                if new is None:
                    continue          # edit didn't apply (tool call failed); file unchanged
            if new != text:
                text = new
                out.append(((ts(e["timestamp"]) - start).total_seconds() / 60, text))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--task", default="v2.2")
    args = ap.parse_args()

    task = run_attempt.TASKS[args.task]
    start_text = open(os.path.join(task["starter"], TARGET)).read()
    vs = versions(os.path.join(args.run_dir, "transcript.jsonl"), start_text)
    real_path = os.path.join(args.run_dir, "workspace", TARGET)
    if os.path.exists(real_path):
        faithful = bool(vs) and vs[-1][1] == open(real_path).read()
    else:
        faithful = None      # no real final file (e.g. workspace lost): rebuild can't be verified
    print(f"{len(vs)} versions; rebuilt final matches real final: {faithful}")

    scorer = run_attempt.load_v2_scorer(task["dir"])
    cases = [json.loads(l) for path in task["cases"] for l in open(path)]
    rows_out = []
    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "snapshot")
        os.makedirs(pkg)
        open(os.path.join(pkg, "__init__.py"), "w").close()
        for minute, text in vs:
            with open(os.path.join(pkg, "ignore.py"), "w") as f:
                f.write(text)
            s = scorer.summarize(scorer.score(os.path.join(pkg, "ignore.py"), cases))
            missing = [k.split("_")[0] for k, v in s["by_rule"].items() if v["rate"] < 0.5]
            rows_out.append({"minute": round(minute, 1), "score": s["score"], "weak_rules": missing})
            print(f"  {minute:5.1f} min  {s['score']:6.1%}  weak: {','.join(missing) or '-'}", flush=True)
    json.dump({"faithful": faithful, "versions": rows_out},
              open(os.path.join(args.run_dir, "score_over_time.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
