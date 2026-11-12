"""Alternative 296x240 layouts for the cube's Claude usage face.

Pick one by writing its letter to face_style.txt (default "C"); push_face.py uses render().
  A bars    - stacked rows, big %, thick bars
  B rings   - two ring gauges side by side
  C hero    - giant 5-hour number, week as a footer line (default)
  D native  - matches the cube's own cyan UI: panels and pill segments
  E paper   - light cream, two columns
  F type    - numbers only, as large as they fit
"""
import math
import os
import time

from PIL import Image, ImageDraw

import render_face as rf

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 296, 240
AV, MONO = rf.TITLE, rf.MONO          # Avenir Next.ttc, Menlo.ttc
AV_BOLD, AV_DEMI, AV_MED = 0, 2, 5
F = rf._font

# warm dark palette (Claude-ish)
BG, CORAL, CREAM, GREY, TRACK = rf.C_BG, rf.C_CORAL, rf.C_CREAM, rf.C_GREY, rf.C_TRACK
AMBER, RED = (240, 170, 60), (232, 72, 72)


def level(p, ok=CORAL, warn=AMBER, crit=RED):
    return crit if p >= 90 else warn if p >= 70 else ok


def values(usage, now):
    out = []
    for key in ("five_hour", "seven_day"):
        b = usage.get(key) or {}
        p, r = b.get("pct", 0.0), b.get("resets_at")
        if r and r <= now:
            p = 0.0
        out += [p, r]
    return out  # p5, r5, p7, r7


def brand(d, x, y, size, ink=CREAM, mark=CORAL):
    """Spark + 'Claude'; (x, y) = spark centre."""
    rf._spark(d, x, y, size * 0.55, mark)
    d.text((x + size * 0.85, y + size * 0.42), "Claude", font=F(AV, size, AV_DEMI), fill=ink, anchor="ls")


def pill(d, box, fill, r=None):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=r if r is not None else (y1 - y0) // 2, fill=fill)


def bar(d, x0, y0, x1, y1, p, track, color):
    pill(d, (x0, y0, x1, y1), track)
    h = y1 - y0
    pill(d, (x0, y0, x0 + max(h, int((x1 - x0) * min(p, 100) / 100)), y1), color)


# --------------------------------------------------------------------------- A
def style_a(usage, now):
    return rf.render(usage, now)


# --------------------------------------------------------------------------- B
def style_b(usage, now):
    p5, r5, p7, r7 = values(usage, now)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    brand(d, 28, 26, 24)
    d.text((W - 26, 35), "usage", font=F(MONO, 15), fill=GREY, anchor="rs")
    for cx, label, p, r in ((76, "5H", p5, r5), (220, "7D", p7, r7)):
        cy, R, wd = 130, 56, 14
        box = (cx - R, cy - R, cx + R, cy + R)
        d.arc(box, 0, 360, fill=TRACK, width=wd)
        col = level(p)
        if p > 0:
            end = -90 + 360 * min(p, 100) / 100
            d.arc(box, -90, end, fill=col, width=wd)
            rr = R - wd / 2
            for a in (-90, end):  # round caps
                ax, ay = cx + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a))
                d.ellipse((ax - wd / 2, ay - wd / 2, ax + wd / 2, ay + wd / 2), fill=col)
        d.text((cx, cy - 2), f"{p:.0f}%", font=F(MONO, 30, 1), fill=CREAM, anchor="mm")
        d.text((cx, cy + 24), label, font=F(AV, 16, AV_DEMI), fill=CORAL, anchor="mm")
        d.text((cx, cy + R + 22), rf._left(r, now), font=F(MONO, 17, 1), fill=GREY, anchor="mm")
    return im


# --------------------------------------------------------------------------- C
def style_c(usage, now):
    p5, r5, p7, r7 = values(usage, now)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # The real screen has rounded corners and a bezel lip: keep corner items well inside.
    brand(d, 34, 30, 22)
    d.text((W - 30, 38), "5-hour", font=F(MONO, 15), fill=GREY, anchor="rs")
    d.text((W // 2, 124), f"{p5:.0f}%", font=F(MONO, 84, 1), fill=level(p5, ok=CREAM), anchor="ms")
    bar(d, 18, 136, W - 18, 154, p5, TRACK, level(p5))
    d.text((W // 2, 178), "resets in " + rf._left(r5, now), font=F(MONO, 16, 1), fill=GREY, anchor="ms")
    d.line((30, 190, W - 30, 190), fill=TRACK, width=2)
    d.text((36, 216), "7D", font=F(AV, 21, AV_DEMI), fill=CORAL, anchor="ls")
    bar(d, 72, 203, 194, 215, p7, TRACK, level(p7))
    d.text((W - 36, 217), f"{p7:.0f}%", font=F(MONO, 22, 1), fill=CREAM, anchor="rs")
    return im


# --------------------------------------------------------------------------- D
N_BG, N_PANEL, N_EDGE, N_INK = (115, 230, 239), (236, 252, 253), (36, 128, 148), (22, 92, 110)
N_SOFT, N_EMPTY, N_FILL = (70, 140, 155), (186, 232, 238), (214, 74, 148)


def style_d(usage, now):
    p5, r5, p7, r7 = values(usage, now)
    im = Image.new("RGB", (W, H), N_BG)
    d = ImageDraw.Draw(im)
    # notch line like the cube's own settings screen
    d.line([(30, 44), (104, 44), (116, 52), (180, 52), (192, 44), (266, 44)], fill=N_EDGE, width=3, joint="curve")
    tw = d.textlength("Claude", font=F(AV, 24, AV_BOLD))
    x = W / 2 - (tw + 26) / 2
    rf._spark(d, x + 10, 22, 12, CORAL)
    d.text((x + 26, 31), "Claude", font=F(AV, 24, AV_BOLD), fill=N_INK, anchor="ls")
    for y, label, p, r in ((60, "5H", p5, r5), (150, "7D", p7, r7)):
        d.rounded_rectangle((12, y, W - 12, y + 84), radius=16, fill=N_PANEL, outline=N_EDGE, width=3)
        d.text((28, y + 32), label, font=F(AV, 24, AV_BOLD), fill=N_INK, anchor="ls")
        d.text((70, y + 31), rf._left(r, now), font=F(MONO, 16, 1), fill=N_SOFT, anchor="ls")
        d.text((W - 28, y + 34), f"{p:.0f}%", font=F(MONO, 32, 1), fill=N_INK, anchor="rs")
        n, gap, x0, x1 = 12, 4, 28, W - 28
        pw = (x1 - x0 - gap * (n - 1)) / n
        lit = math.ceil(min(p, 100) / 100 * n) if p > 0 else 0
        col = level(p, ok=N_FILL)
        for i in range(n):
            px = x0 + i * (pw + gap)
            pill(d, (round(px), y + 46, round(px + pw), y + 70), col if i < lit else N_EMPTY)
    return im


# --------------------------------------------------------------------------- E
P_BG, P_INK, P_CORAL, P_GREY, P_TRACK, P_RULE = (240, 238, 230), (31, 30, 29), (196, 98, 66), (118, 113, 103), (221, 216, 203), (205, 199, 185)


def style_e(usage, now):
    p5, r5, p7, r7 = values(usage, now)
    im = Image.new("RGB", (W, H), P_BG)
    d = ImageDraw.Draw(im)
    brand(d, 28, 26, 24, ink=P_INK, mark=P_CORAL)
    d.text((W - 26, 35), "usage", font=F(MONO, 15), fill=P_GREY, anchor="rs")
    d.line((14, 48, W - 14, 48), fill=P_RULE, width=2)
    d.line((148, 64, 148, 222), fill=P_RULE, width=2)
    for x0, cap, p, r in ((14, "5 HOURS", p5, r5), (162, "7 DAYS", p7, r7)):
        d.text((x0, 80), cap, font=F(AV, 16, AV_DEMI), fill=P_CORAL, anchor="ls")
        d.text((x0, 140), f"{p:.0f}%", font=F(MONO, 48, 1), fill=P_INK, anchor="ls")
        bar(d, x0, 156, x0 + 120, 172, p, P_TRACK, level(p, ok=P_CORAL, warn=(214, 140, 30), crit=(200, 50, 50)))
        d.text((x0, 202), "resets " + rf._left(r, now), font=F(MONO, 15, 1), fill=P_GREY, anchor="ls")
    return im


# --------------------------------------------------------------------------- F
def style_f(usage, now):
    p5, r5, p7, r7 = values(usage, now)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    brand(d, 20, 18, 19)
    for y0, label, p, r in ((34, "5H", p5, r5), (138, "7D", p7, r7)):
        d.text((14, y0 + 44), label, font=F(AV, 34, AV_BOLD), fill=CORAL, anchor="ls")
        d.text((14, y0 + 76), rf._left(r, now), font=F(MONO, 17, 1), fill=GREY, anchor="ls")
        d.text((W - 10, y0 + 80), f"{p:.0f}%", font=F(MONO, 72, 1), fill=level(p, ok=CREAM), anchor="rs")
    d.line((14, 136, W - 14, 136), fill=TRACK, width=2)
    return im


STYLES = {"A": style_a, "B": style_b, "C": style_c, "D": style_d, "E": style_e, "F": style_f}
NAMES = {"A": "Bars", "B": "Rings", "C": "Session hero", "D": "Cube native", "E": "Paper", "F": "Big type"}


def selected():
    try:
        s = open(os.path.join(HERE, "face_style.txt")).read().strip().upper()
        return s if s in STYLES else "C"
    except OSError:
        return "C"


def render(usage, now=None, style=None) -> Image.Image:
    return STYLES[style or selected()](usage, now or time.time())


if __name__ == "__main__":
    now = time.time()
    samples = {
        "normal": {"five_hour": {"pct": 42, "resets_at": now + 2 * 3600 + 12 * 60},
                   "seven_day": {"pct": 18, "resets_at": now + 6 * 86400 + 3 * 3600}},
        "high": {"five_hour": {"pct": 88, "resets_at": now + 35 * 60},
                 "seven_day": {"pct": 93, "resets_at": now + 2 * 86400 + 5 * 3600}},
    }
    out = os.path.join(HERE, "face_options")
    os.makedirs(out, exist_ok=True)
    for state, u in samples.items():
        for k, fn in STYLES.items():
            fn(u, now).save(os.path.join(out, f"{k}-{state}.png"))
    sheet = Image.new("RGB", (W * 3 + 40, (H + 10) * 4 + 10), (60, 60, 60))
    for i, (state, k) in enumerate((s, k) for s in samples for k in STYLES):
        im = Image.open(os.path.join(out, f"{k}-{state}.png"))
        row, col = divmod(i, 3)
        sheet.paste(im, (10 + col * (W + 10), 10 + row * (H + 10)))
    sheet.save(os.path.join(out, "_sheet.png"))
    print("wrote", out)
