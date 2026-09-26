#!/usr/bin/env python3
"""
Mirror a Convex query result to a JSON file.

Runs as its own process on purpose: the Convex Python client's blocking
`next()` holds the GIL, which starves other Python threads in the same
process. Keeping the subscription in a separate process keeps the renderer
and HTTP server completely unaffected.

  ./venv/bin/python convex_subscriber.py --game-id <id> --out /tmp/qz-state.json
"""
import argparse
import json
import os
import signal
import tempfile
import time

from convex import ConvexClient


def write_atomic(path: str, obj) -> None:
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--convex-url", default=os.environ.get("CONVEX_URL"))
    ap.add_argument("--out", default=os.environ.get("STATE_FILE", "/tmp/qz-state.json"))
    a = ap.parse_args()
    if not a.convex_url:
        ap.error("--convex-url or CONVEX_URL required")

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))

    client = ConvexClient(a.convex_url)
    print(f"subscriber: game={a.game_id} url={a.convex_url} -> {a.out}", flush=True)

    while not stop["v"]:
        try:
            for value in client.subscribe("games:gameState", {"gameId": a.game_id}):
                if stop["v"]:
                    break
                write_atomic(a.out, {"ts": time.time(), "state": value})
                print(f"  push phase={value.get('phase')}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"subscription error: {type(e).__name__}: {e}; retrying", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
