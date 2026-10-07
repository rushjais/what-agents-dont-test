#!/bin/zsh
# Create a long-lived Claude Code token and save it for --sandbox docker, without copy-paste.
# Runs `claude setup-token`, captures its terminal output to a private temp file,
# extracts the token (it wraps across lines), saves it with 600 perms, deletes the capture.
set -e
dir="$HOME/.config/snapshot-task"
mkdir -p "$dir" && chmod 700 "$dir"
log="$(mktemp "$dir/capture.XXXXXX")"
trap 'rm -f "$log"' EXIT

# Drop variables inherited from the Claude desktop app; they break CLI auth.
for v in ${(k)parameters[(I)CLAUDE*]} ANTHROPIC_BASE_URL; do unset $v; done

script -q "$log" claude setup-token

python3 - "$log" "$dir/oauth_token" <<'EOF'
import os, re, sys
raw = open(sys.argv[1], errors="replace").read()
text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r", "", raw)
lines = text.split("\n")
for i, line in enumerate(lines):
    m = re.search(r"sk-ant-oat[0-9]+-[A-Za-z0-9_-]+", line)
    if m:
        tok = m.group(0)
        for nxt in lines[i + 1:]:
            nxt = nxt.strip()
            if re.fullmatch(r"[A-Za-z0-9_-]+", nxt):
                tok += nxt
            else:
                break
        break
else:
    sys.exit("\nNo token found in the output. Nothing saved.")
fd = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, tok.encode())
os.close(fd)
print(f"\nsaved ({len(tok)} characters). You can close this tab.")
EOF
