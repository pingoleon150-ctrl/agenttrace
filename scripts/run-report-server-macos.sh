#!/bin/zsh
set -eu

script_directory=${0:A:h}
repository_directory=${script_directory:h}
site_directory=${AGENTTRACE_SITE_DIRECTORY:-"$repository_directory/reports/site"}
host=${AGENTTRACE_REPORT_HOST:-0.0.0.0}
port=${AGENTTRACE_REPORT_PORT:-8765}

cd "$site_directory"
exec /usr/bin/python3 -m http.server "$port" --bind "$host"
