#!/usr/bin/env bash
# Start the Party Quiz server + the live TV stream.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8080}"
export STREAM_DIR="${STREAM_DIR:-/tmp/qz-stream}"
export PORT
mkdir -p "$STREAM_DIR"

start_one () {  # name command...
  local name="$1"; shift
  local pidfile="$STREAM_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "  $name already running (pid $(cat "$pidfile"))"
    return 0
  fi
  rm -f "$pidfile"
  QZ_PIDFILE="$pidfile" setsid "$@" >"$STREAM_DIR/$name.log" 2>&1 </dev/null &
  for _ in $(seq 1 16); do
    [ -f "$pidfile" ] && break
    sleep 0.5
  done
  if [ -f "$pidfile" ]; then
    echo "  $name started (pid $(cat "$pidfile"))"
  else
    echo "  $name FAILED to start; see $STREAM_DIR/$name.log"
    tail -5 "$STREAM_DIR/$name.log" || true
    return 1
  fi
}

echo "starting Party Quiz..."
start_one server   ./venv/bin/python server.py
start_one tvstream ./venv/bin/python tvstream.py

TV_IP="${TV_IP:-}"
if [ -n "$TV_IP" ]; then
  start_one watchdog ./venv/bin/python watchdog.py --ip "$TV_IP"
else
  echo "  (watchdog disabled: run with TV_IP=<tv-ip> to auto-recover the TV)"
fi

sleep 2
IP="$(hostname -I | awk '{print $1}')"
echo
echo "  TV screen (live stream) : http://$IP:$PORT/stream/out.m3u8"
echo "  Phones join             : http://$IP:$PORT/join"
echo "  Host console            : http://$IP:$PORT/host"
echo "  HTML screen (browser)   : http://$IP:$PORT/screen"
echo
echo "cast it to a TV with:  ./venv/bin/python cast_tv.py --ip <tv-ip>"
