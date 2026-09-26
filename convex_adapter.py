#!/usr/bin/env python3
"""
Convex -> TV adapter.

Subscribes to the `games:gameState` query on a Convex deployment and drives the
same Pillow -> ffmpeg -> HLS pipeline as the original game. This is the whole
point of the migration: the box becomes a dumb display adapter, and all game
logic lives in Convex.

  ./venv/bin/python convex_adapter.py --game-id <id> --convex-url http://127.0.0.1:3210

Notes:
  * The Python client returns every number as a float (JSON), so we coerce.
  * A dedicated ConvexClient is used ONLY by the subscription thread. Sharing a
    client between the subscription and other calls can deadlock.
  * Countdowns are derived locally from `phaseEndsAt`, so nothing has to poll.
"""
import argparse
import io
import json
import math
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

STREAM_DIR = os.environ.get("STREAM_DIR", "/tmp/qz-convex-stream")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PLAYLIST = "out.m3u8"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def as_int(x, default=None):
    if x is None:
        return default
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Convex -> render.py state
# --------------------------------------------------------------------------
def to_render_state(s: dict, join_url: str) -> dict:
    phase = s.get("phase") or "lobby"
    seconds_left = None
    if phase == "question" and s.get("phaseEndsAt"):
        seconds_left = max(0, int(math.ceil(float(s["phaseEndsAt"]) / 1000.0 - time.time())))
    return {
        "phase": phase,
        "qi": as_int(s.get("questionIndex"), -1),
        "q_total": as_int(s.get("questionCount"), 0),
        "cat": s.get("cat"),
        "question": s.get("question"),
        "options": s.get("options") or [],
        "answer": as_int(s.get("answer")),
        "counts": [as_int(c, 0) for c in (s.get("counts") or [0, 0, 0, 0])],
        "answered": as_int(s.get("answered"), 0),
        "player_count": as_int(s.get("playerCount"), 0),
        "players": [{"name": p.get("name", "?")} for p in (s.get("players") or [])],
        "ranking": [
            {"name": r.get("name", "?"), "score": as_int(r.get("score"), 0), "rank": as_int(r.get("rank"), 0)}
            for r in (s.get("ranking") or [])
        ],
        "seconds_left": seconds_left,
        "duration": as_int(s.get("questionSeconds"), 20),
        "lan_url": join_url,
    }


def idle_state(join_url: str) -> dict:
    return to_render_state({"phase": "lobby", "questionIndex": -1, "questionCount": 0,
                            "players": [], "ranking": [], "playerCount": 0,
                            "answered": 0, "counts": [0, 0, 0, 0]}, join_url)


# --------------------------------------------------------------------------
# State comes from a separate process (convex_subscriber.py) via a JSON file,
# because the Convex Python client's blocking next() starves other threads.
# --------------------------------------------------------------------------
def read_state(path: str):
    try:
        with open(path) as f:
            return json.load(f).get("state")
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# HLS + static web server
# --------------------------------------------------------------------------
class FastHTTPServer(ThreadingHTTPServer):
    """HTTPServer calls socket.getfqdn() during bind, which can block for a long
    time on some networks (and did here once the Convex runtime was up)."""

    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class Handler(BaseHTTPRequestHandler):
    convex_url = ""
    game_id = ""

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Required: the Cast receiver fetches the HLS playlist and segments via
        # XHR, so without CORS it sees the responses as blocked and refuses to
        # play (the requests still land here, which is why it looks like the
        # receiver "fetches the playlist then ignores it").
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        print(f"  {self.client_address[0]} {self.command} {path}", flush=True)
        if path == "/config.json":
            body = json.dumps({"convexUrl": self.convex_url, "gameId": self.game_id})
            return self._send(200, body, "application/json")
        if path.startswith("/stream/"):
            name = os.path.basename(path)
            full = os.path.join(STREAM_DIR, name)
            if not os.path.isfile(full):
                return self._send(404, "not found", "text/plain")
            with open(full, "rb") as f:
                data = f.read()
            ctype = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
            return self._send(200, data, ctype)
        # static frontend
        name = "index.html" if path in ("/", "/join", "/host") else os.path.basename(path)
        full = os.path.join(WEB_DIR, name)
        if os.path.isfile(full):
            ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript",
                     "css": "text/css"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
            with open(full, "rb") as f:
                return self._send(200, f.read(), ctype)
        return self._send(404, "not found", "text/plain")


# --------------------------------------------------------------------------
# ffmpeg pipeline
# --------------------------------------------------------------------------
class Streamer:
    def __init__(self, fps, ffmpeg):
        self.fps = fps
        self.ffmpeg = ffmpeg
        self.proc = None

    def start(self):
        os.makedirs(STREAM_DIR, exist_ok=True)
        for f in os.listdir(STREAM_DIR):
            if f.endswith((".ts", ".m3u8")):
                try:
                    os.remove(os.path.join(STREAM_DIR, f))
                except OSError:
                    pass
        cmd = [
            self.ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "image2pipe", "-framerate", str(self.fps), "-vcodec", "png", "-i", "-",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", "1", "-keyint_min", "1", "-sc_threshold", "0", "-bf", "0",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "12",
            "-hls_flags", "delete_segments+omit_endlist+independent_segments",
            "-hls_segment_filename", os.path.join(STREAM_DIR, "seg%05d.ts"),
            os.path.join(STREAM_DIR, PLAYLIST),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=open(os.path.join(STREAM_DIR, "ffmpeg.log"), "ab"))

    def write(self, img):
        buf = io.BytesIO()
        img.save(buf, format="png", compress_level=1)
        try:
            self.proc.stdin.write(buf.getvalue())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--convex-url", default=os.environ.get("CONVEX_URL"))
    ap.add_argument("--state-file", default=os.environ.get("STATE_FILE", "/tmp/qz-state.json"))
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--ffmpeg", default=os.environ.get("FFMPEG", os.path.expanduser("~/.local/bin/ffmpeg")))
    a = ap.parse_args()

    join_url = f"http://{lan_ip()}:{a.port}/join"

    streamer = Streamer(a.fps, a.ffmpeg)
    streamer.start()

    srv = FastHTTPServer(("0.0.0.0", a.port), Handler)
    Handler.convex_url = a.convex_url or os.environ.get("CONVEX_URL", "")
    Handler.game_id = a.game_id
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print(f"convex adapter: game={a.game_id} state={a.state_file}", flush=True)
    print(f"  TV stream : http://{lan_ip()}:{a.port}/stream/{PLAYLIST}", flush=True)
    print(f"  phones    : {join_url}", flush=True)

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))

    interval = 1.0 / a.fps
    while not stop["v"]:
        t0 = time.time()
        raw = read_state(a.state_file)
        rs = to_render_state(raw, join_url) if raw else idle_state(join_url)
        try:
            streamer.write(render.render(rs))
        except Exception as e:  # noqa: BLE001
            print("render error:", e, flush=True)
        dt = time.time() - t0
        if dt < interval:
            time.sleep(interval - dt)
    print("adapter stopped", flush=True)


if __name__ == "__main__":
    main()
