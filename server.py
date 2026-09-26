#!/usr/bin/env python3
"""
Party Quiz — TV host screen + phones as controllers.

Run:  ./venv/bin/python server.py
Then: cast http://<lan-ip>:8080/screen to the TV, and have phones open
      http://<lan-ip>:8080/join  (QR code is shown on screen automatically).

Pure stdlib + segno (for the QR code). No websockets: everyone polls
/api/state, which keeps it simple and works through any Cast receiver.
"""
import collections
import io
import json
import os
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import segno

PORT = int(os.environ.get("PORT", "8080"))
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
STREAM_DIR = os.environ.get("STREAM_DIR", "/tmp/qz-stream")

QUESTION_SECS = 20
REVEAL_SECS = 8
SCORES_SECS = 7
MAX_POINTS = 1000


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LAN_IP = os.environ.get("LAN_IP") or lan_ip()

# --------------------------------------------------------------------------
# Quiz bank — general knowledge / fun. a = index of the correct option.
# --------------------------------------------------------------------------
QUESTIONS = [
    {"cat": "Geography", "q": "Which country has the most natural lakes?",
     "options": ["Canada", "Russia", "Finland", "Brazil"], "a": 0},
    {"cat": "Science", "q": "What is the most abundant gas in Earth's atmosphere?",
     "options": ["Oxygen", "Carbon dioxide", "Nitrogen", "Argon"], "a": 2},
    {"cat": "Music", "q": "Which instrument has 88 keys?",
     "options": ["Organ", "Piano", "Accordion", "Harpsichord"], "a": 1},
    {"cat": "Movies", "q": "Which film features the line \u201cYou're gonna need a bigger boat\u201d?",
     "options": ["Jaws", "Titanic", "The Perfect Storm", "Deep Blue Sea"], "a": 0},
    {"cat": "History", "q": "In which year did the Berlin Wall fall?",
     "options": ["1985", "1987", "1989", "1991"], "a": 2},
    {"cat": "Nature", "q": "What is a group of flamingos called?",
     "options": ["A flamboyance", "A murder", "A gaggle", "A parliament"], "a": 0},
    {"cat": "Space", "q": "Which planet spins on its side?",
     "options": ["Neptune", "Uranus", "Saturn", "Mercury"], "a": 1},
    {"cat": "Food", "q": "Sushi originated in which country?",
     "options": ["China", "Korea", "Japan", "Vietnam"], "a": 2},
    {"cat": "Tech", "q": "What does \u201cHTTP\u201d stand for?",
     "options": ["HyperText Transfer Protocol", "High Transfer Text Process",
                 "Hyperlink Text Transmission Protocol", "Host Transfer Type Protocol"], "a": 0},
    {"cat": "Animals", "q": "How many hearts does an octopus have?",
     "options": ["One", "Two", "Three", "Five"], "a": 2},
    {"cat": "Geography", "q": "Which is the longest river in the world?",
     "options": ["Amazon", "Nile", "Yangtze", "Mississippi"], "a": 1},
    {"cat": "Sports", "q": "How many players are on the field per team in soccer?",
     "options": ["9", "10", "11", "12"], "a": 2},
    {"cat": "Art", "q": "Who painted the Mona Lisa?",
     "options": ["Michelangelo", "Raphael", "Leonardo da Vinci", "Donatello"], "a": 2},
    {"cat": "Science", "q": "What is the hardest natural substance on Earth?",
     "options": ["Quartz", "Diamond", "Titanium", "Obsidian"], "a": 1},
    {"cat": "Music", "q": "Which band released the album \u201cThe Dark Side of the Moon\u201d?",
     "options": ["The Beatles", "Led Zeppelin", "Pink Floyd", "The Who"], "a": 2},
    {"cat": "Geography", "q": "What is the smallest country in the world by area?",
     "options": ["Monaco", "Nauru", "Vatican City", "San Marino"], "a": 2},
    {"cat": "Nature", "q": "Which animal never sleeps?",
     "options": ["Bullfrog", "Giraffe", "Dolphin", "Sloth"], "a": 0},
    {"cat": "History", "q": "Who was the first person to walk on the Moon?",
     "options": ["Buzz Aldrin", "Neil Armstrong", "Yuri Gagarin", "Michael Collins"], "a": 1},
    {"cat": "Tech", "q": "What year was the first iPhone released?",
     "options": ["2005", "2007", "2009", "2010"], "a": 1},
    {"cat": "Food", "q": "Which spice is the most expensive by weight?",
     "options": ["Vanilla", "Saffron", "Cardamom", "Cinnamon"], "a": 1},
    {"cat": "Movies", "q": "Which movie won the first Academy Award for Best Picture?",
     "options": ["Wings", "Metropolis", "Sunrise", "The Jazz Singer"], "a": 0},
    {"cat": "Animals", "q": "What is the fastest land animal?",
     "options": ["Lion", "Pronghorn", "Cheetah", "Greyhound"], "a": 2},
    {"cat": "Science", "q": "What is the chemical symbol for gold?",
     "options": ["Ag", "Au", "Gd", "Go"], "a": 1},
    {"cat": "Geography", "q": "How many time zones does Russia span?",
     "options": ["7", "9", "11", "13"], "a": 2},
]

# --------------------------------------------------------------------------
# Game state
# --------------------------------------------------------------------------
_lock = threading.Lock()
_game = {}


def new_game():
    return {
        "phase": "lobby",          # lobby | question | reveal | scores | final
        "phase_until": None,
        "deadline": None,
        "qi": -1,
        "players": {},             # pid -> dict
        "order": [],
        "questions": QUESTIONS,
        "duration": QUESTION_SECS,
    }


def new_pid():
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))


def _answered_count(g):
    qi = g["qi"]
    return sum(1 for pid in g["order"] if qi in g["players"][pid]["answers"])


def _enter_reveal(g, now):
    qi = g["qi"]
    q = g["questions"][qi]
    dur = g["duration"]
    for pid in g["order"]:
        ans = g["players"][pid]["answers"].get(qi)
        if not ans:
            continue
        correct = ans["choice"] == q["a"]
        remaining = max(0.0, g["deadline"] - ans["t"])
        ans["correct"] = correct
        ans["points"] = int(500 + 500 * (remaining / dur)) if correct else 0
        g["players"][pid]["score"] += ans["points"]
    g["phase"] = "reveal"
    g["phase_until"] = now + REVEAL_SECS


def _next_question(g, now):
    g["qi"] += 1
    if g["qi"] >= len(g["questions"]):
        g["phase"] = "final"
        g["phase_until"] = None
        return
    g["phase"] = "question"
    g["deadline"] = now + g["duration"]
    g["phase_until"] = None


def tick(g):
    """Advance the state machine. Caller holds the lock."""
    now = time.time()
    if g["phase"] == "question":
        if now >= g["deadline"] or _answered_count(g) >= len(g["order"]) > 0:
            _enter_reveal(g, now)
    elif g["phase"] == "reveal":
        if g["phase_until"] and now >= g["phase_until"]:
            g["phase"] = "scores"
            g["phase_until"] = now + SCORES_SECS
    elif g["phase"] == "scores":
        if g["phase_until"] and now >= g["phase_until"]:
            _next_question(g, now)


def serialize(g, pid=None):
    now = time.time()
    qi = g["qi"]
    q = g["questions"][qi] if 0 <= qi < len(g["questions"]) else None
    show_answer = g["phase"] in ("reveal", "scores", "final")

    counts = [0, 0, 0, 0]
    if q:
        for p in g["players"].values():
            a = p["answers"].get(qi)
            if a:
                counts[a["choice"]] += 1

    ranking = sorted(
        ({"pid": p, "name": g["players"][p]["name"], "score": g["players"][p]["score"]}
         for p in g["order"]),
        key=lambda x: (-x["score"], x["name"].lower()),
    )
    for i, r in enumerate(ranking):
        r["rank"] = i + 1

    out = {
        "phase": g["phase"],
        "qi": qi,
        "q_total": len(g["questions"]),
        "cat": q["cat"] if q else None,
        "question": q["q"] if q else None,
        "options": q["options"] if q else [],
        "answer": q["a"] if (q and show_answer) else None,
        "counts": counts,
        "answered": _answered_count(g) if q else 0,
        "player_count": len(g["order"]),
        "players": [{"name": g["players"][p]["name"]} for p in g["order"]],
        "ranking": ranking,
        "seconds_left": (max(0, int(round(g["deadline"] - now))) if g["phase"] == "question" else None),
        "duration": g["duration"],
        "lan_url": f"http://{LAN_IP}:{PORT}/join",
        "now": now,
    }
    if pid and pid in g["players"]:
        p = g["players"][pid]
        ans = p["answers"].get(qi) if q else None
        out["you"] = {
            "name": p["name"],
            "score": p["score"],
            "rank": next((r["rank"] for r in ranking if r["pid"] == pid), None),
            "choice": ans["choice"] if ans else None,
            "correct": ans.get("correct") if ans else None,
            "points": ans.get("points") if ans else None,
        }
    return out


# --------------------------------------------------------------------------
# Request stats (so we can prove the TV is really rendering/polling)
# --------------------------------------------------------------------------
STATS = {"paths": collections.Counter(), "clients": collections.defaultdict(collections.Counter)}
_stats_lock = threading.Lock()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
MIME = {".html": "text/html; charset=utf-8", ".png": "image/png",
        ".js": "application/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    server_version = "PartyQuiz/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the console quiet

    # -- helpers ----------------------------------------------------------
    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _note(self):
        path = urlparse(self.path).path
        with _stats_lock:
            STATS["paths"][path] += 1
            STATS["clients"][self.client_address[0]][path] += 1

    def _static(self, name):
        path = os.path.join(STATIC, name)
        if not os.path.isfile(path):
            return self._send(404, "not found")
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(os.path.splitext(name)[1], "application/octet-stream"))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        self._note()
        u = urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)
        pid = (qs.get("pid") or [None])[0]

        if p == "/":
            return self._static("index.html")
        if p == "/screen":
            return self._static("screen.html")
        if p in ("/join", "/play", "/player"):
            return self._static("player.html")
        if p == "/host":
            return self._static("host.html")
        if p == "/api/state":
            with _lock:
                tick(_game)
                return self._json(serialize(_game, pid))
        if p.startswith("/stream/"):
            name = os.path.basename(p[len("/stream/"):])
            path = os.path.join(STREAM_DIR, name)
            if not os.path.isfile(path):
                return self._send(404, "not found")
            with open(path, "rb") as f:
                data = f.read()
            ct = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
            return self._send(200, data, ct)
        if p == "/api/stats":
            with _stats_lock:
                return self._json({"paths": dict(STATS["paths"]),
                                   "clients": {k: dict(v) for k, v in STATS["clients"].items()}})
        if p == "/qr.png":
            url = (qs.get("u") or [f"http://{LAN_IP}:{PORT}/join"])[0]
            buf = io.BytesIO()
            segno.make(url, error="m").save(buf, kind="png", scale=9, border=1, dark="#000000", light="#ffffff")
            return self._send(200, buf.getvalue(), "image/png")
        return self._send(404, "not found")

    def do_POST(self):
        self._note()
        p = urlparse(self.path).path.rstrip("/") or "/"
        data = self._body()

        if p == "/api/join":
            name = (data.get("name") or "").strip()[:16] or "Player"
            with _lock:
                base, n = name, 2
                while any(pl["name"] == name for pl in _game["players"].values()):
                    name = f"{base} ({n})"
                    n += 1
                pid = new_pid()
                _game["players"][pid] = {"name": name, "score": 0, "answers": {}}
                _game["order"].append(pid)
                return self._json({"pid": pid, "name": name, "state": serialize(_game, pid)})

        if p == "/api/answer":
            pid, choice = data.get("pid"), data.get("choice")
            with _lock:
                tick(_game)
                if _game["phase"] != "question":
                    return self._json({"ok": False, "error": "not accepting answers"}, 409)
                if pid not in _game["players"] or not isinstance(choice, int) or not 0 <= choice <= 3:
                    return self._json({"ok": False, "error": "bad request"}, 400)
                ans = _game["players"][pid]["answers"]
                if _game["qi"] not in ans:  # lock in the first answer
                    ans[_game["qi"]] = {"choice": choice, "t": time.time()}
                tick(_game)
                return self._json({"ok": True, "state": serialize(_game, pid)})

        if p == "/api/host":
            action = data.get("action")
            with _lock:
                tick(_game)
                now = time.time()
                if action == "start" and _game["phase"] == "lobby":
                    _next_question(_game, now)
                elif action == "reveal" and _game["phase"] == "question":
                    _enter_reveal(_game, now)
                elif action == "scores" and _game["phase"] == "reveal":
                    _game["phase"], _game["phase_until"] = "scores", now + SCORES_SECS
                elif action == "next":
                    _next_question(_game, now)
                elif action == "add_time" and _game["phase"] == "question":
                    _game["deadline"] += 10
                elif action == "restart":
                    _game.clear()
                    _game.update(new_game())
                else:
                    return self._json({"ok": False, "error": f"bad action {action!r}"}, 400)
                return self._json({"ok": True, "state": serialize(_game)})

        return self._send(404, "not found")


def main():
    global _game
    _game = new_game()
    pidfile = os.environ.get("QZ_PIDFILE")
    if pidfile:
        with open(pidfile, "w") as f:
            f.write(str(os.getpid()))
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Party Quiz on http://{LAN_IP}:{PORT}")
    print(f"   TV screen : http://{LAN_IP}:{PORT}/screen")
    print(f"   phones    : http://{LAN_IP}:{PORT}/join")
    print(f"   host      : http://{LAN_IP}:{PORT}/host")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
