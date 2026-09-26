#!/usr/bin/env python3
"""
Live TV stream for Party Quiz.

Renders the quiz screen with Pillow at ~1 fps and pipes the frames into
ffmpeg, which produces a rolling HLS playlist. The Cast device just plays
  http://<box>:8080/stream/out.m3u8
as a normal live stream -- no DashCast, no browser needed.
"""
import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8080/api/state")
OUT_DIR = os.environ.get("STREAM_DIR", "/tmp/qz-stream")
FPS = float(os.environ.get("FPS", "1"))
FFMPEG = os.environ.get("FFMPEG", os.path.expanduser("~/.local/bin/ffmpeg"))
PLAYLIST = os.path.join(OUT_DIR, "out.m3u8")

_ff = None


def start_ffmpeg():
    global _ff
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith((".ts", ".m3u8")):
            try:
                os.remove(os.path.join(OUT_DIR, f))
            except OSError:
                pass
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(FPS), "-vcodec", "png", "-i", "-",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", "1", "-keyint_min", "1", "-sc_threshold", "0", "-bf", "0",
        "-f", "hls", "-hls_time", "1", "-hls_list_size", "12",
        "-hls_flags", "delete_segments+omit_endlist+independent_segments",
        "-hls_segment_filename", os.path.join(OUT_DIR, "seg%05d.ts"),
        PLAYLIST,
    ]
    _ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                           stderr=open(os.path.join(OUT_DIR, "ffmpeg.log"), "ab"))
    return _ff


def fetch_state():
    try:
        with urllib.request.urlopen(STATE_URL, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def main():
    global _ff
    stop = {"v": False}

    def _sig(*_):
        stop["v"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    start_ffmpeg()
    pidfile = os.environ.get("QZ_PIDFILE")
    if pidfile:
        with open(pidfile, "w") as f:
            f.write(str(os.getpid()))
    print(f"streaming -> http://0.0.0.0:8080/stream/out.m3u8  ({FPS} fps)", flush=True)
    last_state = None
    interval = 1.0 / FPS
    while not stop["v"]:
        t0 = time.time()
        s = fetch_state()
        if s is None:
            if last_state is None:
                time.sleep(1)
                continue
            s = last_state
        last_state = s
        try:
            img = render.render(s)
            buf = io.BytesIO()
            img.save(buf, format="png", optimize=False, compress_level=1)
            _ff.stdin.write(buf.getvalue())
            _ff.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            # ffmpeg died -> restart it
            try:
                _ff.stdin.close()
            except Exception:
                pass
            start_ffmpeg()
            continue
        dt = time.time() - t0
        if dt < interval:
            time.sleep(interval - dt)
    try:
        _ff.stdin.close()
    except Exception:
        pass
    _ff.wait(timeout=5)
    print("stream stopped", flush=True)


if __name__ == "__main__":
    main()
