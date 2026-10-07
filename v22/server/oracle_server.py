"""The `packignore` black box: serves the reference implementation over HTTP.

    python3 v2/server/oracle_server.py --port 8765

Runs on the HOST, never in the agent's sandbox, so the agent can query the
tool but can't read or decompile it. The agent's client (starter/tools/
packignore) sends a tree's file list and .packignore contents; this replies
with the files the reference excludes.

POST /ignored  body: a tar archive of the tree (files with contents and permissions)
     -> 200    {"ignored": ["rel/path", ...]}

v2.2: the engine also looks at file contents and permissions, so the client
uploads the whole tree as a tar. That's generic on purpose: the client's code
shouldn't reveal which file properties matter.
"""

import argparse
import io
import json
import stat
import tarfile
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference"))
import packignore  # noqa: E402

MAX_BODY = 20_000_000
MAX_FILES = 5_000
MAX_LINE = 1_000       # characters per .packignore line
MAX_LINES = 2_000      # lines per .packignore file
MAX_DEPTH = 64         # path segments


def check_tar(members):
    """Plain-language problem with the uploaded tree, or None. Generic messages only."""
    files = [m for m in members if m.isfile()]
    if len(files) > MAX_FILES:
        return f"too many files (limit {MAX_FILES})"
    paths = set()
    for m in members:
        rel = m.name.removeprefix("./")
        segs = rel.split("/")
        if m.issym() or m.islnk() or not (m.isfile() or m.isdir()):
            return f"unsupported entry (only regular files and directories): {rel!r}"
        if not rel or rel.startswith("/") or "\x00" in rel or any(x in ("", ".", "..") for x in segs):
            return f"invalid path: {rel!r}"
        if len(segs) > MAX_DEPTH:
            return f"path too deep (limit {MAX_DEPTH} levels)"
        if m.isfile():
            paths.add(rel)
    for rel in paths:
        parts = rel.split("/")
        for k in range(1, len(parts)):
            if "/".join(parts[:k]) in paths:
                return f"invalid tree: {'/'.join(parts[:k])!r} is both a file and a directory"
    return None


def check_ignore_file(text):
    lines = text.splitlines()
    if len(lines) > MAX_LINES or any(len(l) > MAX_LINE for l in lines):
        return f"ignore file too large (limits: {MAX_LINES} lines, {MAX_LINE} characters per line)"
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
            tar = tarfile.open(fileobj=io.BytesIO(self.rfile.read(n)), mode="r:*")
            members = tar.getmembers()
        except Exception:
            return self._reply(400, {"error": "malformed request: expected a tar archive"})
        problem = check_tar(members)
        if problem:
            return self._reply(413 if "too" in problem else 400, {"error": problem})
        try:
            with tempfile.TemporaryDirectory() as root:
                for m in members:
                    rel = m.name.removeprefix("./")
                    path = os.path.join(root, rel)
                    if m.isdir():
                        os.makedirs(path, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    data = tar.extractfile(m).read()
                    if os.path.basename(rel) == packignore.IGNORE_FILE:
                        problem = check_ignore_file(data.decode("utf-8", "replace"))
                        if problem:
                            return self._reply(413, {"error": problem})
                    with open(path, "wb") as f:
                        f.write(data)
                    os.chmod(path, 0o755 if m.mode & 0o111 else 0o644)
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
