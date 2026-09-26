#!/usr/bin/env python3
"""Generate the README screenshots from fake game states.

  python tools/make_screenshots.py

Writes docs/screenshot-*.png. Needs Pillow + segno (see requirements.txt).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import render  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.normpath(os.path.join(HERE, "..", "docs"))

BASE = {
    "qi": 2,
    "q_total": 24,
    "cat": "Geography",
    "question": "Which country has the most natural lakes?",
    "options": ["Canada", "Russia", "Finland", "Brazil"],
    "answer": None,
    "counts": [0, 0, 0, 0],
    "answered": 0,
    "player_count": 4,
    "players": [{"name": n} for n in ("Ada", "Grace", "Linus", "Margaret")],
    "ranking": [
        {"name": "Ada", "score": 2870, "rank": 1},
        {"name": "Linus", "score": 2610, "rank": 2},
        {"name": "Grace", "score": 1940, "rank": 3},
        {"name": "Margaret", "score": 1720, "rank": 4},
    ],
    "seconds_left": 20,
    "duration": 20,
    "lan_url": "http://192.168.1.50:8080/join",
}


def state(**kw):
    s = dict(BASE)
    s.update(kw)
    return s


SHOTS = {
    "lobby": state(phase="lobby", qi=-1, question=None, options=[], cat=None,
                   seconds_left=None),
    "question": state(phase="question", answered=2, seconds_left=13),
    "reveal": state(phase="reveal", answer=0, counts=[3, 0, 1, 0],
                    answered=4, seconds_left=None),
    "scores": state(phase="scores", seconds_left=None),
    "final": state(phase="final", qi=24, question=None, options=[], cat=None,
                  seconds_left=None),
}


def main():
    os.makedirs(DOCS, exist_ok=True)
    for name, s in SHOTS.items():
        path = os.path.join(DOCS, f"screenshot-{name}.png")
        render.render(s).save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
