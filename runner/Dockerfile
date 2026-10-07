# Sandbox for one agent attempt: Python 3.11 (no pathspec), git, and Claude Code.
# Only the attempt's workspace is mounted in; nothing else from the host is visible.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code \
 && python3 -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('pathspec') is not None)"

# Writable home for whatever uid the runner starts the container as.
ENV HOME=/home/agent
RUN mkdir -p /home/agent && chmod 777 /home/agent \
 && git config --system user.name dev && git config --system user.email dev@example.com \
 && git config --system --add safe.directory '*'

WORKDIR /work/repo
