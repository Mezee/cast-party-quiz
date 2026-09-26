#!/usr/bin/env python3
"""Cast the Party Quiz live stream to a TV.

  ./venv/bin/python cast_tv.py                      # Living Room TV
  ./venv/bin/python cast_tv.py --ip 192.168.40.223
  ./venv/bin/python cast_tv.py --name "Master Bedroom TV"
"""
import argparse
import socket
import sys
import time

import pychromecast


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", help="TV IP address, e.g. 192.168.1.50")
    ap.add_argument("--name", help="TV name for mDNS discovery, e.g. 'Living Room TV'")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--volume", type=float, default=None, help="0.0-1.0")
    ap.add_argument("--url", default=None)
    a = ap.parse_args()
    if not a.ip and not a.name:
        ap.error("give either --ip or --name")

    url = a.url or f"http://{lan_ip()}:{a.port}/stream/out.m3u8"

    if a.ip:
        c = pychromecast.get_chromecast_from_host((a.ip, 8009, None, None, None), timeout=20)
    else:
        casts, _ = pychromecast.get_chromecasts(timeout=15)
        c = next((x for x in casts if x.name == a.name), None)
        if c is None:
            sys.exit(f"device {a.name!r} not found; discovered: {[x.name for x in casts]}")
    c.wait(timeout=25)
    print(f"target: {c.name or a.ip} (app was {c.status.app_id})")

    try:
        c.quit_app()
        time.sleep(4)
    except Exception:
        pass
    if a.volume is not None:
        c.set_volume(a.volume)
    c.media_controller.play_media(url, "application/x-mpegurl", stream_type="LIVE")
    print("casting live stream:", url)
    for _ in range(15):
        time.sleep(2)
        c.media_controller.update_status()
        st = c.media_controller.status.player_state
        print("  state:", st)
        if st == "PLAYING":
            print("OK - playing on TV")
            return
    print("warning: did not reach PLAYING state")


if __name__ == "__main__":
    main()
