#!/usr/bin/env bash
# Stop the Party Quiz server + live stream (pidfile based; no pkill).
set -uo pipefail
cd "$(dirname "$0")"
STREAM_DIR="${STREAM_DIR:-/tmp/qz-stream}"
PORT="${PORT:-8080}"

for name in watchdog tvstream server; do
  p="$STREAM_DIR/$name.pid"
  if [ -f "$p" ]; then
    pid="$(cat "$p")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "stopped $name (pid $pid)"
    fi
    rm -f "$p"
  fi
done

# fallback: whoever holds the port
PID=$(ss -ltnp 2>/dev/null | sed -n "s/.*:$PORT .*pid=\([0-9]*\).*/\1/p" | head -1)
if [ -n "${PID:-}" ]; then
  kill "$PID" 2>/dev/null && echo "stopped server holding :$PORT (pid $PID)"
fi
echo "done"
