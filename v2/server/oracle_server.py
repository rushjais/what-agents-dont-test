"""The `packignore` black box: serves the reference implementation over HTTP.

    python3 v2/server/oracle_server.py --port 8765

Runs on the HOST, never in the agent's sandbox, so the agent can query the
tool but can't read or decompile it. The agent's client (starter/tools/
packignore) sends a tree's file list and .packignore contents; this replies
with the files the reference excludes.

POST /ignored  {"files": {"rel/path": "<content of .packignore files, else null>"}}
     -> 200    {"ignored": ["rel/path", ...]}
"""

import argparse
import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference"))
import packignore  # noqa: E402

MAX_BODY = 5_000_000
MAX_FILES = 5_000
MAX_LINE = 1_000       # characters per .packignore line
MAX_LINES = 2_000      # lines per .packignore file
MAX_DEPTH = 64         # path segments


def check_input(files):
    """Return a plain-language problem with the request, or None.

    Limits are far above anything in the hidden cases; they exist so one huge
    or malformed request can't stall the oracle for the rest of a run. The
    messages are deliberately generic: they say what's wrong with the request,
    never anything about how the oracle works inside.
    """
    if len(files) > MAX_FILES:
        return f"too many files (limit {MAX_FILES})"
    paths = set()
    for rel, content in files.items():
        segs = rel.split("/")
        if (not isinstance(rel, str) or not rel or rel.startswith("/") or "\x00" in rel
                or any(s in ("", ".", "..") for s in segs)):
            return f"invalid path: {rel!r}"
        if len(segs) > MAX_DEPTH:
            return f"path too deep (limit {MAX_DEPTH} levels)"
        if content is not None:
            if not isinstance(content, str):
                return f"invalid content for {rel!r}"
            lines = content.splitlines()
            if len(lines) > MAX_LINES or any(len(l) > MAX_LINE for l in lines):
                return f"ignore file too large (limits: {MAX_LINES} lines, {MAX_LINE} characters per line)"
        paths.add(rel)
    for rel in paths:
        parts = rel.split("/")
        for k in range(1, len(parts)):
            if "/".join(parts[:k]) in paths:
                return f"invalid tree: {'/'.join(parts[:k])!r} is both a file and a directory"
    return None


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/ignored":
            return self._reply(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BODY:
            return self._reply(413, {"error": "request too large"})
        try:
            files = json.loads(self.rfile.read(n))["files"]
            assert isinstance(files, dict)
        except Exception:
            return self._reply(400, {"error": "malformed request"})
        problem = check_input(files)
        if problem:
            return self._reply(400 if "invalid" in problem else 413, {"error": problem})
        try:
            with tempfile.TemporaryDirectory() as root:
                for rel, content in files.items():
                    path = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", newline="") as f:
                        f.write("x\n" if content is None else content)
                return self._reply(200, {"ignored": packignore.ignored_files(root)})
        except Exception as e:
            # Never send internals (paths, tracebacks) to the agent: the oracle is a black box.
            sys.stderr.write(f"oracle error: {type(e).__name__}: {e}\n")
            return self._reply(500, {"error": "internal error"})

    def log_message(self, fmt, *args):
        if self.server.log:
            sys.stderr.write("%s\n" % (fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.log = args.log
    print(f"packignore oracle on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
