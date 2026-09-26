#!/usr/bin/env python3
"""
Render the quiz screen to a PIL image, fast enough for a live video stream
on a weak ARM box. Mirrors the design of static/screen.html.
"""
import io

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

BG = (18, 18, 28)
PANEL = (29, 29, 46)
INK = (245, 245, 255)
DIM = (154, 160, 181)
GREEN = (126, 231, 135)
GOLD = (255, 209, 102)
OPTC = [(226, 27, 60), (19, 104, 206), (216, 158, 0), (38, 137, 12)]
SHAPES = ["\u25B2", "\u25C6", "\u25CF", "\u25A0"]

_fonts = {}


def F(size, bold=True):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(BOLD if bold else REG, size)
    return _fonts[key]


def wrap(draw, text, font, maxw):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def background():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):  # subtle top glow
        t = max(0.0, 1 - y / (H * 0.75))
        c = (int(BG[0] + 24 * t), int(BG[1] + 24 * t), int(BG[2] + 46 * t))
        d.line([(0, y), (W, y)], fill=c)
    return img, d


def pill(d, x, y, text, fg=DIM, bg=PANEL, pad=18, size=22):
    f = F(size)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + pad * 2, y + size + pad], radius=(size + pad) // 2, fill=bg)
    d.text((x + pad, y + pad // 2), text, font=f, fill=fg)
    return x + w + pad * 2


def centre(d, y, text, font, fill, x0=0, x1=W):
    w = d.textlength(text, font=font)
    d.text((x0 + (x1 - x0 - w) / 2, y), text, font=font, fill=fill)


def header(d, s):
    left = f"Q{s['qi']+1} / {s['q_total']}" if s["qi"] >= 0 else "Lobby"
    x = pill(d, 40, 30, left, INK, PANEL, size=24)
    if s.get("cat"):
        pill(d, x + 14, 30, s["cat"], GOLD, PANEL, size=24)
    n = s["player_count"]
    label = f"{n} player" + ("" if n == 1 else "s")
    w = d.textlength(label, font=F(24))
    pill(d, W - 40 - (w + 36), 30, label, INK, PANEL, size=24)


def qr_image(url, px=300):
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=10, border=1)
    buf.seek(0)
    return Image.open(buf).convert("RGB").resize((px, px), Image.NEAREST)


def lobby(d, s):
    f = F(78)
    centre(d, 60, "PARTY QUIZ", f, INK)
    qr = qr_image(s["lan_url"], 320)
    d.rounded_rectangle([90, 210, 90 + 320 + 24, 210 + 320 + 24], radius=20, fill=(255, 255, 255))
    d._image.paste(qr, (102, 222))
    x = 480
    d.text((x, 215), "SCAN TO JOIN, OR OPEN", font=F(26), fill=DIM)
    avail = W - x - 50
    size = 46
    while size > 20 and d.textlength(s["lan_url"], font=F(size)) > avail:
        size -= 2
    d.text((x, 252), s["lan_url"], font=F(size), fill=GREEN)
    d.text((x, 400), "Phones on the same WiFi \u2014 no app needed.", font=F(28), fill=INK)
    d.text((x, 440), "Host: open /host to start the game.", font=F(28), fill=DIM)
    # player chips
    cx, cy = 90, 580
    for p in s["players"][:12]:
        nxt = pill(d, cx, cy, p["name"], INK, PANEL, size=26)
        if nxt > W - 260:
            cx, cy = 90, cy + 56
            nxt = pill(d, cx, cy, p["name"], INK, PANEL, size=26)
        cx = nxt + 14
    msg = "Waiting for the host to start\u2026" if s["player_count"] else "Waiting for players\u2026"
    d.text((W - 430, 592), msg, font=F(24), fill=DIM)


def question(d, s):
    header(d, s)
    reveal = s["phase"] in ("reveal", "scores")
    lines = wrap(d, s["question"], F(40), W - 160)
    y = 120
    for ln in lines[:3]:
        centre(d, y, ln, F(40), INK)
        y += 50
    # timer + progress
    sl = s["seconds_left"]
    ty = y + 6
    if sl is not None:
        low = sl <= 5
        d.ellipse([70, ty, 70 + 84, ty + 84], fill=PANEL, outline=(255, 91, 91) if low else (58, 63, 92), width=6)
        centre(d, ty + 18, str(sl), F(46), (255, 91, 91) if low else INK, 70, 154)
        pct = max(0.0, min(1.0, sl / max(1, s["duration"])))
    else:
        pct = 1.0
    bx0, bx1 = 180, 880
    d.rounded_rectangle([bx0, ty + 36, bx1, ty + 50], radius=7, fill=(42, 42, 69))
    d.rounded_rectangle([bx0, ty + 36, bx0 + int((bx1 - bx0) * pct), ty + 50], radius=7, fill=GREEN)
    d.text((bx1 + 24, ty + 26), f"{s['answered']} / {s['player_count']} answered", font=F(26), fill=DIM)

    # options grid
    maxc = max([1] + s["counts"])
    oy = ty + 110
    for i in range(4):
        col, row = i % 2, i // 2
        x0 = 70 + col * 585
        y0 = oy + row * 110
        x1, y1 = x0 + 555, y0 + 92
        c = OPTC[i]
        if reveal and i != s["answer"]:
            c = tuple(int(v * 0.35) for v in c)
        d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=c)
        if reveal and i == s["answer"]:
            d.rounded_rectangle([x0 - 5, y0 - 5, x1 + 5, y1 + 5], radius=22, outline=(255, 255, 255), width=6)
        d.text((x0 + 26, y0 + 26), SHAPES[i], font=F(38), fill=(255, 255, 255))
        txt = wrap(d, s["options"][i], F(30), 430)[0]
        d.text((x0 + 84, y0 + 28), txt, font=F(30), fill=(255, 255, 255))
        if reveal:
            d.text((x1 - 40, y0 + 20), str(s["counts"][i]), font=F(40), fill=(255, 255, 255))
            bw = int((x1 - x0) * s["counts"][i] / maxc)
            d.rounded_rectangle([x0, y1 - 10, x0 + max(6, bw), y1], radius=5, fill=(255, 255, 255))


def scores(d, s):
    header(d, s)
    centre(d, 110, "SCORES", F(56), INK)
    y = 200
    for r in s["ranking"][:8]:
        top = r["rank"] == 1
        d.rounded_rectangle([180, y, W - 180, y + 56], radius=14,
                            fill=(58, 47, 0) if top else PANEL,
                            outline=GOLD if top else None, width=3)
        medal = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}.get(r["rank"], str(r["rank"]))
        d.text((210, y + 12), medal, font=F(30), fill=GOLD)
        d.text((290, y + 12), r["name"][:22], font=F(30), fill=INK)
        sc = str(r["score"])
        d.text((W - 210 - d.textlength(sc, font=F(30)), y + 12), sc, font=F(30), fill=GREEN)
        y += 64


def final(d, s):
    header(d, s)
    centre(d, 90, "\U0001F3C6 FINAL RESULTS", F(52), INK)
    r = s["ranking"]
    pods = [(1, 430, 150), (0, 700, 190), (2, 970, 120)]
    for rank_i, cx, hgt in pods:
        if rank_i >= len(r):
            continue
        x0, x1 = cx - 100, cx + 100
        y1 = 520
        y0 = y1 - hgt
        d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=PANEL,
                            outline=GOLD if rank_i == 0 else None, width=4)
        centre(d, y0 + 16, r[rank_i]["name"][:14], F(26), INK, x0, x1)
        centre(d, y0 + 52, str(r[rank_i]["score"]), F(24), GREEN, x0, x1)
        centre(d, y1 - 56, str(rank_i + 1), F(52), GOLD, x0, x1)
    y = 545
    for p in r[3:7]:
        d.rounded_rectangle([300, y, W - 300, y + 40], radius=10, fill=PANEL)
        d.text((330, y + 6), f"{p['rank']}.  {p['name'][:24]}", font=F(24), fill=INK)
        d.text((W - 340, y + 6), str(p["score"]), font=F(24), fill=GREEN)
        y += 46


def render(s):
    img, d = background()
    d._image = img  # so helpers can paste
    ph = s["phase"]
    if ph == "lobby":
        lobby(d, s)
    elif ph == "final":
        final(d, s)
    elif ph == "scores":
        scores(d, s)
    else:
        question(d, s)
    return img


if __name__ == "__main__":
    import json
    import sys
    import urllib.request
    state = json.loads(urllib.request.urlopen(sys.argv[1] if len(sys.argv) > 1 else
                                              "http://127.0.0.1:8080/api/state").read())
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/render_test.png"
    render(state).save(out)
    print("wrote", out)
