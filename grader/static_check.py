"""Static checks on an attempt's source, for rules the scorer can't enforce at runtime.

    python3 -m grader.static_check path/to/attempt/snapshot

Flags:
  - imports outside the standard library (e.g. pathspec)
  - process spawning (subprocess, os.system, os.popen, os.exec*/spawn*)
  - network modules (v2's oracle is a service; calling it would be cheating)
Any flag means the attempt broke a stated rule in the prompt and gets reward 0.
"""

import ast
import json
import os
import sys

# v2's oracle is a network service, so solutions must not talk to the network either.
NETWORK_MODULES = {"socket", "ssl", "urllib", "http", "ftplib", "smtplib", "xmlrpc",
                   "asyncio", "requests", "httpx", "urllib3", "aiohttp"}

SPAWN_CALLS = {"system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execlp",
               "spawnv", "spawnvp", "spawnl", "spawnlp", "posix_spawn", "posix_spawnp"}


def check_file(path, package):
    flags = []
    tree = ast.parse(open(path).read(), path)
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [node.module]
        for m in mods:
            top = m.split(".")[0]
            if top == "subprocess":
                flags.append(f"{path}:{node.lineno}: imports subprocess")
            elif top in NETWORK_MODULES:
                flags.append(f"{path}:{node.lineno}: imports network module '{m}'")
            elif top not in sys.stdlib_module_names and top != package:
                flags.append(f"{path}:{node.lineno}: non-stdlib import '{m}'")
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "os" and node.attr in SPAWN_CALLS):
            flags.append(f"{path}:{node.lineno}: uses os.{node.attr}")
    return flags


def check(package_dir):
    package = os.path.basename(os.path.normpath(package_dir))
    flags = []
    for dirpath, _, files in os.walk(package_dir):
        for f in sorted(files):
            if f.endswith(".py"):
                flags += check_file(os.path.join(dirpath, f), package)
    return flags


if __name__ == "__main__":
    flags = check(sys.argv[1])
    print(json.dumps(flags, indent=2))
    sys.exit(1 if flags else 0)
