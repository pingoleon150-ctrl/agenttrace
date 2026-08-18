#!/bin/zsh
set -eu

script_directory=${0:A:h}
repository_directory=${script_directory:h}
cd "$repository_directory"

agenttrace_binary=${AGENTTRACE_BIN:-"$repository_directory/.venv/bin/agenttrace"}
if [[ ! -x "$agenttrace_binary" ]]; then
  agenttrace_binary=$(command -v agenttrace)
fi

if [[ -z "${GITHUB_TOKEN:-}" && -z "${GH_TOKEN:-}" ]]; then
  if [[ -x /opt/homebrew/bin/gh ]]; then
    gh_binary=/opt/homebrew/bin/gh
  elif [[ -x /usr/local/bin/gh ]]; then
    gh_binary=/usr/local/bin/gh
  elif gh_binary=$(command -v gh 2>/dev/null); then
    :
  else
    print -u2 "GitHub CLI not found; install gh or provide GITHUB_TOKEN."
    exit 1
  fi
  export GH_TOKEN
  GH_TOKEN=$("$gh_binary" auth token)
fi

export AGENTTRACE_DB="${AGENTTRACE_DB:-"$repository_directory/agenttrace-monitor.db"}"
monitor_interval=${AGENTTRACE_INTERVAL_SECONDS:-300}
monitor_threshold=${AGENTTRACE_THRESHOLD:-0.75}
query_batch_size=${AGENTTRACE_QUERY_BATCH_SIZE:-2}
history_limit=${AGENTTRACE_HISTORY_LIMIT:-20000}
window_minutes=${AGENTTRACE_WINDOW_MINUTES:-1440}

exec /usr/bin/caffeinate -i "$agenttrace_binary" watch \
  --threshold "$monitor_threshold" \
  --interval "$monitor_interval" \
  --query-batch-size "$query_batch_size" \
  --history-limit "$history_limit" \
  --window-minutes "$window_minutes"
