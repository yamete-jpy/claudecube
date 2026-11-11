"""Draw a 296x240 static 'Claude usage' face for the cube (layout = mock B)."""
import time

from PIL import Image, ImageDraw, ImageFont

W, H = 296, 240
BG = (7, 12, 13)
TEAL = (62, 224, 200)
TRACK = (24, 41, 42)
LABEL = (143, 163, 160)
SUB = (111, 132, 129)
WHITE = (255, 255, 255)
MONO = "/System/Library/Fonts/Menlo.ttc"
TITLE = "/System/Library/Fonts/Avenir Next.ttc"


def _font(path, size, index=0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except OSError:
        return ImageFont.load_default(size)


def _level(p):
    return (255, 90, 90) if p >= 90 else (255, 178, 62) if p >= 70 else TEAL


def _left(resets_at, now):
    """Coarse on purpose so the picture (and the upload) only changes now and then:
    days -> '6d', hours -> '3h', last hour -> 10-minute steps."""
    if not resets_at:
        return ""
    s = max(0, int(resets_at - now))
    h, m = divmod(s // 60, 60)
    if h >= 24:
        return f"{h // 24}d"
    if h >= 1:
        return f"{h}h"
    return f"{max(10, -(-m // 10) * 10)}m" if m else "<10m"


def _bar(d, y, label, pct, sub, f_label, f_big, f_sub):
    d.text((20, y), label, font=f_label, fill=LABEL, anchor="ls")
    d.text((W - 20, y + 6), f"{pct:.0f}%", font=f_big, fill=WHITE, anchor="rs")
    bx, by, bw, bh = 20, y + 14, W - 40, 14
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=7, fill=TRACK)
    fill = max(bh, int(bw * min(pct, 100) / 100))
    d.rounded_rectangle((bx, by, bx + fill, by + bh), radius=7, fill=_level(pct))
    if sub:
        d.text((20, by + bh + 18), sub, font=f_sub, fill=SUB, anchor="ls")


def _row(d, y0, label, pct, sub, f_label, f_big, f_sub):
    """One half of the screen (120 px): big percentage, thick bar, reset time."""
    d.text((14, y0 + 50), f"{pct:.0f}%", font=f_big, fill=WHITE, anchor="ls")
    d.text((W - 14, y0 + 30), label, font=f_label, fill=TEAL, anchor="rs")
    if sub:
        d.text((W - 14, y0 + 52), sub, font=f_sub, fill=LABEL, anchor="rs")
    bx, by, bw, bh = 14, y0 + 64, W - 28, 22
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=11, fill=TRACK)
    fill = max(bh, int(bw * min(pct, 100) / 100))
    d.rounded_rectangle((bx, by, bx + fill, by + bh), radius=11, fill=_level(pct))


C_BG = (25, 24, 22)
C_CORAL = (217, 119, 87)
C_CREAM = (250, 249, 245)
C_GREY = (168, 164, 154)
C_TRACK = (50, 47, 43)


def _c_level(p):
    return (232, 72, 72) if p >= 90 else (240, 170, 60) if p >= 70 else C_CORAL


def _spark(d, cx, cy, r, color, rays=10):
    """A simple tapered starburst mark."""
    import math
    for i in range(rays):
        a = math.pi * 2 * i / rays - math.pi / 2
        ln = r if i % 2 == 0 else r * 0.78
        tip = (cx + ln * math.cos(a), cy + ln * math.sin(a))
        w = r * 0.16
        pa, pb = a + math.pi / 2, a - math.pi / 2
        base1 = (cx + w * math.cos(pa), cy + w * math.sin(pa))
        base2 = (cx + w * math.cos(pb), cy + w * math.sin(pb))
        d.polygon([base1, tip, base2], fill=color)
    d.ellipse((cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2), fill=color)


def _c_row(d, y0, label, pct, sub, f_label, f_big, f_sub):
    """One usage row (~96 px): big percentage, label + reset time, thick bar."""
    d.text((14, y0 + 46), f"{pct:.0f}%", font=f_big, fill=C_CREAM, anchor="ls")
    d.text((W - 14, y0 + 22), label, font=f_label, fill=C_CORAL, anchor="rs")
    if sub:
        d.text((W - 14, y0 + 45), sub, font=f_sub, fill=C_GREY, anchor="rs")
    bx, by, bw, bh = 14, y0 + 58, W - 28, 20
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=C_TRACK)
    fill = max(bh, int(bw * min(pct, 100) / 100))
    d.rounded_rectangle((bx, by, bx + fill, by + bh), radius=10, fill=_c_level(pct))


def render(usage, now=None) -> Image.Image:
    """usage = usage_source.get_usage() dict. 'Claude' header + large-type rows."""
    now = now or time.time()
    im = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(im)
    f_brand = _font(TITLE, 27, index=2)  # Avenir Next Demi Bold
    f_label = _font(TITLE, 26, index=2)
    f_big = _font(MONO, 50, index=1)     # Menlo Bold
    f_sub = _font(MONO, 18, index=1)
    f_time = _font(MONO, 16)

    _spark(d, 28, 24, 15, C_CORAL)
    d.text((52, 35), "Claude", font=f_brand, fill=C_CREAM, anchor="ls")
    d.text((W - 14, 33), "usage", font=f_time, fill=C_GREY, anchor="rs")

    def pct_of(key):
        b = usage.get(key) or {}
        if not b:
            return None, None
        p = b["pct"]
        if b.get("resets_at") and b["resets_at"] <= now:
            p = 0.0
        return p, b.get("resets_at")

    p5, r5 = pct_of("five_hour")
    p7, r7 = pct_of("seven_day")
    if p5 is not None:
        _c_row(d, 46, "5H", p5, _left(r5, now), f_label, f_big, f_sub)
    d.line((14, 144, W - 14, 144), fill=C_TRACK, width=2)
    if p7 is not None:
        _c_row(d, 146, "7D", p7, _left(r7, now), f_label, f_big, f_sub)
    return im


def render_big(usage, now=None) -> Image.Image:
    """Numbers-only large-type layout (no header)."""
    now = now or time.time()
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f_label = _font(TITLE, 30, index=2)  # Avenir Next Demi Bold
    f_big = _font(MONO, 58, index=1)     # Menlo Bold
    f_sub = _font(MONO, 20, index=1)

    def pct_of(key):
        b = usage.get(key) or {}
        if not b:
            return None, None
        p = b["pct"]
        if b.get("resets_at") and b["resets_at"] <= now:
            p = 0.0
        return p, b.get("resets_at")

    p5, r5 = pct_of("five_hour")
    p7, r7 = pct_of("seven_day")
    if p5 is not None:
        _row(d, 8, "5H", p5, _left(r5, now), f_label, f_big, f_sub)
    d.line((14, 120, W - 14, 120), fill=TRACK, width=2)
    if p7 is not None:
        _row(d, 126, "7D", p7, _left(r7, now), f_label, f_big, f_sub)
    return im


def render_small(usage, now=None) -> Image.Image:
    """Original small-type layout with title and clock."""
    now = now or time.time()
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f_title = _font(TITLE, 17, index=2)  # Avenir Next Demi Bold
    f_label = _font(MONO, 13)
    f_big = _font(MONO, 32, index=1)     # Menlo Bold
    f_sub = _font(MONO, 12)
    d.text((20, 32), "CLAUDE USAGE", font=f_title, fill=TEAL, anchor="ls")
    d.text((W - 20, 32), time.strftime("%H:%M", time.localtime(now)), font=f_sub, fill=SUB, anchor="rs")

    def pct_of(key):
        b = usage.get(key) or {}
        if not b:
            return None, None
        p = b["pct"]
        if b.get("resets_at") and b["resets_at"] <= now:
            p = 0.0
        return p, b.get("resets_at")

    p5, r5 = pct_of("five_hour")
    p7, r7 = pct_of("seven_day")
    if p5 is not None:
        _bar(d, 78, "SESSION · 5H", p5, "resets in " + _left(r5, now), f_label, f_big, f_sub)
    if p7 is not None:
        _bar(d, 166, "WEEK · 7D", p7, "resets in " + _left(r7, now), f_label, f_big, f_sub)
    return im


if __name__ == "__main__":
    import sys
    import usage_source
    out = sys.argv[1] if len(sys.argv) > 1 else "face_preview.png"
    render(usage_source.get_usage()).save(out)
    print("saved", out)
