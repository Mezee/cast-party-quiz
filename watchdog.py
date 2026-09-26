#!/usr/bin/env python3
"""Keep the Party Quiz stream alive on a TV.

The reliable signal is NOT the Cast media status (pychromecast often reports
UNKNOWN on a fresh connection even while the TV is playing). Instead we ask
our own server: is the TV still fetching stream segments? If it fetches
nothing for two checks in a row, re-cast.

It also refuses to fight you: if the TV is on a different app (e.g. YouTube),
it leaves it alone.
"""
import argparse
import json
import os
import socket
import time
import urllib.request

import pychromecast

MEDIA_RECEIVER = "CC1AD845"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def stream_requests(tv_ip, port):
    """Total number of /stream/* requests made by the TV so far."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=5) as r:
            d = json.loads(r.read())
    except Exception:
        return None
    return sum(v for k, v in d.get("clients", {}).get(tv_ip, {}).items() if k.startswith("/stream/"))


def app_id(tv_ip):
    try:
        c = pychromecast.get_chromecast_from_host((tv_ip, 8009, None, None, None), timeout=12)
        c.wait(timeout=15)
        return c.status.app_id, c
    except Exception:
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=os.environ.get("TV_IP", ""),
                    help="TV IP address (or set the TV_IP environment variable)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--interval", type=float, default=15)
    a = ap.parse_args()
    if not a.ip:
        ap.error("--ip is required (or set TV_IP)")
    url = f"http://{lan_ip()}:{a.port}/stream/out.m3u8"

    print(f"watchdog: {a.ip} -> {url} (every {a.interval:g}s)", flush=True)
    pidfile = os.environ.get("QZ_PIDFILE")
    if pidfile:
        with open(pidfile, "w") as f:
            f.write(str(os.getpid()))
    last = None
    strikes = 0
    while True:
        total = stream_requests(a.ip, a.port)
        app, cast = app_id(a.ip)
        delta = None if (total is None or last is None) else total - last
        last = total if total is not None else last
        print(f"  app={app} stream_reqs={total} delta={delta} strikes={strikes}", flush=True)

        if app not in (MEDIA_RECEIVER, None):
            # user switched to another app on purpose -- hands off
            strikes = 0
        elif delta == 0:
            strikes += 1
            if strikes >= 2:
                print("  -> TV is not fetching segments; re-casting", flush=True)
                try:
                    if cast is None:
                        cast = pychromecast.get_chromecast_from_host(
                            (a.ip, 8009, None, None, None), timeout=12)
                        cast.wait(timeout=15)
                    cast.media_controller.play_media(url, "application/x-mpegurl",
                                                     stream_type="LIVE")
                except Exception as e:
                    print(f"  re-cast failed: {e}", flush=True)
                strikes = 0
        else:
            strikes = 0
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
