#!/usr/bin/env python3
"""Render a 15s previz animatic of the valkyrie sequence.

The animatic is a motion reference for Seedance: it fixes timing, camera, pose
(fists-first flight) and wing scale (wingspan ~8x body height) so the model only
has to make it photoreal. Upload it as a video reference alongside the character
photos.

    python production/previz.py [out.mp4]

Timeline: shot 1 portal burst 0-4s, shot 2 ocean fly-by 4-8s, shot 3 landing 8-15s.
"""
import math
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H, FPS, DUR = 1280, 720, 24, 15.0
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "renders" / "valkyrie-previz.mp4"

GOLD = (255, 196, 90)
GOLD_DK = (200, 140, 50)
WHITE = (245, 240, 230)
WING = (250, 244, 232)
RED = (170, 20, 30)
SKIN = (225, 175, 140)
HAIR = (215, 140, 80)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_in(x):
    return x * x * x


def ease_out(x):
    return 1 - (1 - x) ** 3


def seg(t, a, b):
    return clamp((t - a) / (b - a))


# ---------------------------------------------------------------- backgrounds
def sky_and_sea(horizon, rocks=False):
    img = Image.new("RGB", (W, H))
    px = np.zeros((H, W, 3), np.float32)
    for y in range(H):
        if y < horizon:
            k = y / horizon
            px[y] = np.array([8, 12, 30]) * (1 - k) + np.array([22, 32, 60]) * k
        else:
            k = (y - horizon) / (H - horizon)
            px[y] = np.array([12, 20, 38]) * (1 - k) + np.array([3, 6, 14]) * k
    img = Image.fromarray(px.astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(7)
    # clouds
    for _ in range(40):
        cx, cy = rnd.uniform(0, W), rnd.uniform(0, horizon * 0.7)
        r = rnd.uniform(40, 140)
        d.ellipse([cx - r * 2, cy - r * 0.5, cx + r * 2, cy + r * 0.5], fill=(40, 50, 80, 40))
    # moon + glow
    mx, my = 1010, 110
    glow = Image.new("L", (W, H))
    ImageDraw.Draw(glow).ellipse([mx - 60, my - 60, mx + 60, my + 60], fill=160)
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    img = Image.composite(Image.new("RGB", (W, H), (200, 210, 235)), img, glow)
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse([mx - 34, my - 34, mx + 34, my + 34], fill=(236, 238, 245))
    # moon reflection on water
    for i in range(70):
        y = horizon + 4 + i * (H - horizon) / 70
        w = rnd.uniform(4, 40) * (1 + i / 40)
        ox = rnd.uniform(-25, 25) * (1 + i / 30)
        d.line([mx + ox - w, y, mx + ox + w, y], fill=(200, 210, 235, rnd.randint(30, 90)), width=2)
    # skyline: towers, opera house sails, harbour bridge
    for i in range(26):
        x = 150 + i * 20 + rnd.uniform(-4, 4)
        h = rnd.uniform(14, 70) * (1.4 if 8 < i < 16 else 1)
        d.rectangle([x, horizon - h, x + 15, horizon], fill=(20, 24, 40))
        for _ in range(4):
            d.point((x + rnd.uniform(2, 9), horizon - rnd.uniform(2, h)), fill=(255, 210, 140))
    for i, (x, h) in enumerate([(690, 26), (708, 34), (726, 24), (742, 30)]):
        d.polygon([(x, horizon), (x + 16, horizon - h), (x + 26, horizon)], fill=(225, 222, 212))
    d.arc([790, horizon - 60, 990, horizon + 50], 180, 360, fill=(70, 70, 85), width=5)
    d.line([790, horizon - 4, 990, horizon - 4], fill=(70, 70, 85), width=3)
    for x in range(790, 990, 6):
        d.point((x, horizon - 2), fill=(255, 200, 120))
    if rocks:
        rr = random.Random(3)
        for i in range(14):
            x = -60 + i * 100 + rr.uniform(-30, 30)
            y = 560 + rr.uniform(-25, 25)
            pts = [(x + rr.uniform(-20, 20) + 70 * math.cos(a), y + 50 * math.sin(a) * 0.6)
                   for a in np.linspace(math.pi, 2 * math.pi, 7)]
            d.polygon(pts + [(x + 80, H), (x - 80, H)], fill=(28 + i % 3 * 6, 28, 32))
        d.rectangle([0, 600, W, H], fill=(30, 30, 34))
    return img


# ---------------------------------------------------------------- figure
def tf(pts, cx, cy, s, rot=0.0):
    c, sn = math.cos(rot), math.sin(rot)
    return [(cx + s * (x * c - y * sn), cy + s * (x * sn + y * c)) for x, y in pts]


def ellipse_pts(x, y, rx, ry, n=16):
    return [(x + rx * math.cos(a), y + ry * math.sin(a)) for a in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def wing_pts(root, tip, up, n=9):
    """Feathered wing: arched leading edge root->tip, scalloped trailing edge back."""
    rx, ry = root
    tx, ty = tip
    lead = []
    for i in range(n + 1):
        k = i / n
        x = rx + (tx - rx) * k
        y = ry + (ty - ry) * k + up * math.sin(k * math.pi)
        lead.append((x, y))
    trail = []
    depth = 0.55
    for i in range(n, -1, -1):
        k = i / n
        x, y = lead[i]
        dx, dy = tx - rx, ty - ry
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L, dx / L
        if ny < 0:
            nx, ny = -nx, -ny
        dd = depth * (1 - 0.6 * k) * (1.25 if i % 2 else 0.9)
        trail.append((x + nx * dd, y + ny * dd))
    return lead + trail


def draw_figure(layer, glow, view, cx, cy, s, rot=0.0, wing_open=1.0, crouch=0.0, fists_up=0.0):
    d = ImageDraw.Draw(layer)
    g = ImageDraw.Draw(glow)
    polys = []  # (points, colour, glows)

    if view == "front_fly":  # flying straight at camera, fists leading
        for sgn in (-1, 1):
            polys.append((wing_pts((0.12 * sgn, -0.12), (4.0 * sgn, -0.9), -0.5), WING, True))
        polys.append((ellipse_pts(0, 0.28, 0.06, 0.12), GOLD_DK, False))  # legs behind
        polys.append((ellipse_pts(0, 0.05, 0.16, 0.2), WHITE, False))
        polys.append(([(-0.1, -0.05), (0, 0.15), (0.1, -0.05), (0.05, -0.05), (0, 0.06), (-0.05, -0.05)], RED, False))
        polys.append((ellipse_pts(0, 0.2, 0.15, 0.06), RED, False))
        polys.append((ellipse_pts(0, -0.2, 0.2, 0.14), HAIR, False))
        polys.append((ellipse_pts(0, -0.18, 0.1, 0.12), GOLD, True))
        for sgn in (-1, 1):
            polys.append(([(0.08 * sgn, -0.24), (0.2 * sgn, -0.42), (0.13 * sgn, -0.22)], GOLD, True))
            polys.append(([(0.16 * sgn, -0.08), (0.1 * sgn, 0.02), (0.05 * sgn, -0.02), (0.12 * sgn, -0.12)], SKIN, False))
            polys.append((ellipse_pts(0.075 * sgn, 0.0, 0.07, 0.07), GOLD, True))  # fists, nearest camera
    elif view == "side_fly":  # horizontal, heading +x, fists leading
        polys.append((wing_pts((0.2, -0.05), (-3.6, -1.9), -0.6), (215, 208, 196), True))  # far wing
        polys.append(([(0.55, 0.0), (0.2, -0.08), (-0.2, -0.12), (-0.4, -0.05), (-0.2, 0.0)], HAIR, False))
        polys.append(([(-0.05, -0.02), (-0.55, 0.0), (-0.55, 0.05), (-0.05, 0.07)], GOLD_DK, False))  # legs
        polys.append((ellipse_pts(0.0, 0.03, 0.1, 0.07), RED, False))  # skirt
        polys.append((ellipse_pts(0.22, 0.02, 0.17, 0.08), WHITE, False))
        polys.append(([(0.12, -0.03), (0.22, 0.05), (0.32, -0.03)], RED, False))
        polys.append(([(0.35, -0.02), (0.8, -0.04), (0.8, 0.02), (0.35, 0.04)], SKIN, False))  # arms
        polys.append((ellipse_pts(0.84, -0.01, 0.06, 0.05), GOLD, True))  # fists
        polys.append((ellipse_pts(0.48, -0.02, 0.08, 0.07), GOLD, True))  # helmet
        polys.append(([(0.45, -0.07), (0.38, -0.2), (0.5, -0.08)], GOLD, True))
        polys.append((wing_pts((0.2, 0.02), (-3.4, 1.7), 0.5), WING, True))  # near wing
    else:  # "stand": front, shore; crouch 0..1, wing_open 0..1, fists_up 0..1
        dy = 0.3 * crouch
        o = wing_open
        for sgn in (-1, 1):
            tip = (sgn * (0.5 + 3.6 * o), -1.9 + 0.8 * o + dy)
            polys.append((wing_pts((0.1 * sgn, -0.35 + dy), tip, -0.4 - 0.2 * o), WING, True))
        for sgn in (-1, 1):  # legs: knees out when crouched
            hip = (0.07 * sgn, 0.05 + dy)
            knee = (0.16 * sgn + 0.12 * sgn * crouch, 0.3 + dy * 0.6)
            foot = (0.14 * sgn + 0.08 * sgn * crouch, 0.55)
            polys.append(([hip, knee, (knee[0] + 0.06 * sgn, knee[1]), (foot[0] + 0.05 * sgn, foot[1]),
                           (foot[0] - 0.02 * sgn, foot[1]), (hip[0] + 0.02 * sgn, hip[1])], GOLD_DK, False))
        polys.append((ellipse_pts(0, 0.05 + dy, 0.15, 0.08), RED, False))
        polys.append((ellipse_pts(0, -0.15 + dy, 0.13, 0.2), WHITE, False))
        polys.append(([(-0.1, -0.3 + dy), (0, -0.1 + dy), (0.1, -0.3 + dy), (0.05, -0.3 + dy), (0, -0.18 + dy), (-0.05, -0.3 + dy)], RED, False))
        polys.append((ellipse_pts(0, -0.43 + dy, 0.14, 0.18), HAIR, False))
        polys.append((ellipse_pts(0, -0.45 + dy, 0.08, 0.1), GOLD, True))
        for sgn in (-1, 1):
            polys.append(([(0.06 * sgn, -0.5 + dy), (0.16 * sgn, -0.66 + dy), (0.1 * sgn, -0.48 + dy)], GOLD, True))
            sh = (0.15 * sgn, -0.3 + dy)
            if sgn > 0 and crouch > 0.5:  # three-point landing: right fist on the ground
                fist = (0.25, 0.5)
            else:
                fist = (0.14 * sgn, -0.02 + dy - 0.3 * fists_up)
            polys.append(([sh, (sh[0] + 0.05 * sgn, sh[1]), (fist[0] + 0.03 * sgn, fist[1]), (fist[0] - 0.03 * sgn, fist[1])], SKIN, False))
            polys.append((ellipse_pts(fist[0], fist[1], 0.05, 0.05), GOLD, True))

    for pts, col, glows in polys:
        p = tf(pts, cx, cy, s, rot)
        d.polygon(p, fill=col + (255,))
        if glows:
            g.polygon(p, fill=255)
        if col in (WING, (215, 208, 196)) and s > 20:
            half = len(p) // 2
            lw = max(1, int(s / 90))
            for i in range(1, half):  # feather shafts: leading edge -> scalloped tip
                d.line([p[i], p[len(p) - 1 - i]], fill=(190, 175, 150, 255), width=lw)
            for i in range(1, half - 1):  # secondary coverts row
                a, b = p[i], p[len(p) - 1 - i]
                m = ((a[0] * 2 + b[0]) / 3, (a[1] * 2 + b[1]) / 3)
                n2 = ((p[i + 1][0] * 2 + p[len(p) - 2 - i][0]) / 3, (p[i + 1][1] * 2 + p[len(p) - 2 - i][1]) / 3)
                d.line([m, n2], fill=(205, 190, 165, 255), width=lw)


# ---------------------------------------------------------------- fx
def lightning(d, a, b, rnd, width=3, col=(255, 235, 180, 255), jag=18):
    pts = [a]
    n = 8
    for i in range(1, n):
        k = i / n
        pts.append((a[0] + (b[0] - a[0]) * k + rnd.uniform(-jag, jag), a[1] + (b[1] - a[1]) * k + rnd.uniform(-jag, jag)))
    pts.append(b)
    d.line(pts, fill=col, width=width)


class Spray:
    def __init__(self):
        self.p = []

    def emit(self, x, y, n, rnd, spread=6.0, up=10.0, size=8):
        for _ in range(n):
            self.p.append([x + rnd.uniform(-10, 10), y, rnd.uniform(-spread, spread), -rnd.uniform(up * 0.4, up), rnd.uniform(size * 0.5, size * 1.5), 1.0])

    def step(self, dt):
        for q in self.p:
            q[0] += q[2] * dt * 24
            q[1] += q[3] * dt * 24
            q[3] += 0.5 * dt * 24
            q[5] -= dt * 0.45
        self.p = [q for q in self.p if q[5] > 0]

    def draw(self, d):
        for x, y, _, _, r, life in self.p:
            a = int(160 * life)
            d.ellipse([x - r, y - r * 1.2, x + r, y + r * 1.2], fill=(235, 240, 250, a))


# ---------------------------------------------------------------- shots
BG1 = sky_and_sea(420)
BG3 = sky_and_sea(400, rocks=True)
spray2 = Spray()
dust3 = Spray()
_last = {"t": -1}


def frame(t):
    rnd = random.Random(int(t * 1000))
    shake = 0.0
    flash = 0.0
    if t < 4.0:  # ---- shot 1: portal burst, static low angle
        img = BG1.copy()
        fig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow = Image.new("L", (W, H))
        fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(fx)
        pcx, pcy = 640, 330
        r = 150 * ease_out(seg(t, 0.5, 1.2))
        if r > 2:
            for k in range(6):
                d.ellipse([pcx - r - k * 3, pcy - r * 1.05 - k * 3, pcx + r + k * 3, pcy + r * 1.05 + k * 3], outline=(255, 190 + k * 10, 90 + k * 25, 255 - k * 30), width=6)
            ImageDraw.Draw(glow).ellipse([pcx - r - 20, pcy - r - 20, pcx + r + 20, pcy + r + 20], outline=255, width=40)
            for _ in range(5):
                a = rnd.uniform(0, 2 * math.pi)
                a2 = a + rnd.uniform(0.3, 1.0)
                lightning(d, (pcx + r * math.cos(a), pcy + r * math.sin(a)), (pcx + (r + rnd.uniform(40, 160)) * math.cos(a2), pcy + (r + rnd.uniform(40, 160)) * math.sin(a2)), rnd)
        if 0.45 < t < 0.6:
            flash = 0.6
        # shockwave on the water
        sw = seg(t, 1.3, 2.6)
        if 0 < sw < 1:
            R = 60 + 900 * ease_out(sw)
            d.ellipse([pcx - R, 440 - R * 0.08, pcx + R, 440 + R * 0.08], outline=(230, 235, 245, int(220 * (1 - sw))), width=10)
        # valkyrie bursts at camera: 1.4s -> 3.3s, scale explodes
        k = seg(t, 1.4, 3.3)
        if k > 0:
            s = 18 + 700 * ease_in(k)
            cy = pcy + 60 * k
            draw_figure(fig, glow, "front_fly", pcx, cy, s)
            shake = 14 * seg(t, 2.8, 3.3)
        flash = max(flash, seg(t, 3.25, 3.5) * (1 - seg(t, 3.7, 4.0)))
        layers = [fx, fig]
    elif t < 8.0:  # ---- shot 2: low side-angle fly-by
        lt = t - 4.0
        img = BG1.copy()
        fig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow = Image.new("L", (W, H))
        fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(fx)
        dt = 1 / FPS
        if _last["t"] < 4.0 or lt < dt:
            spray2.p.clear()
        k = seg(lt, 0.2, 2.0)
        e = k ** 2.2
        wx = 330 + 1250 * e          # water point beneath her: far left background -> right foreground
        wy = 426 + 330 * e
        s = 14 + 520 * e ** 1.3
        if 0 < k < 1:
            draw_figure(fig, glow, "front_fly", wx, wy - 0.55 * s - 6, s, rot=0.12)
            # V-wake: walls of spray thrown out to both sides of her path
            for side in (-1, 1):
                spray2.p.extend(
                    [wx + rnd.uniform(-8, 8) + side * 0.2 * s, wy, side * rnd.uniform(1, 3 + 10 * e), -rnd.uniform(3 + 8 * e, 8 + 26 * e),
                     rnd.uniform(2, 3 + 12 * e), 1.0] for _ in range(int(8 + 30 * e)))
            for _ in range(2):
                lightning(d, (wx, wy - 0.55 * s), (wx - rnd.uniform(0.6, 1.4) * s, wy - 0.55 * s - rnd.uniform(0.1, 0.5) * s), rnd, width=2, jag=0.05 * s + 3)
        spray2.step(dt)
        sp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        spray2.draw(ImageDraw.Draw(sp))
        fx.alpha_composite(sp.filter(ImageFilter.GaussianBlur(2)))
        shake = 16 * seg(lt, 1.3, 1.8) * (1 - seg(lt, 2.2, 3.0))
        layers = [fig, fx]
    else:  # ---- shot 3: shoreline landing
        lt = t - 8.0
        img = BG3.copy()
        fig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow = Image.new("L", (W, H))
        fx = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(fx)
        dt = 1 / FPS
        if _last["t"] < 8.0:
            dust3.p.clear()
        gx, gy, S = 640, 600, 250  # feet position and body scale
        cy = gy - 0.55 * S
        if lt < 0.9:  # plummet from above, fist down, wings swept up
            k = ease_in(seg(lt, 0.3, 0.9))
            if lt > 0.3:
                yy = -400 + (cy + 400) * k
                draw_figure(fig, glow, "stand", gx, yy, S, wing_open=0.0, crouch=0.6, fists_up=0)
                ImageDraw.Draw(glow).line([(gx, 0), (gx, yy)], fill=200, width=30)
        else:
            crouch = 1.0 - ease_out(seg(lt, 1.8, 2.8))
            wo = ease_out(seg(lt, 2.9, 3.5)) * (1 - 0.04 * seg(lt, 3.5, 4.0) * (0.5 + 0.5 * math.sin(lt * 2.2)))
            fu = ease_out(seg(lt, 2.2, 2.9))
            pulse = 0.5 + 0.5 * math.sin(lt * 5)
            draw_figure(fig, glow, "stand", gx, cy, S, wing_open=wo, crouch=crouch, fists_up=fu)
            if lt > 3.5:
                for _ in range(2):
                    a = (gx + rnd.uniform(-0.3, 0.3) * S, cy + rnd.uniform(-0.5, 0.3) * S)
                    lightning(d, a, (a[0] + rnd.uniform(-60, 60), a[1] + rnd.uniform(-60, 60)), rnd, width=2, jag=10)
            if 0.9 <= lt < 0.9 + dt * 1.5:
                dust3.emit(gx, gy, 260, rnd, spread=22, up=9, size=14)
                for i in range(9):  # cracks
                    a = rnd.uniform(0, math.pi)
                    ImageDraw.Draw(BG3).line([(gx, gy), (gx + 300 * math.cos(a), gy + 40 * math.sin(a))], fill=(12, 12, 14), width=3)
            flash = 0.8 * (1 - seg(lt, 0.9, 1.2))
            shake = 18 * (1 - seg(lt, 0.9, 1.6))
            glow = Image.eval(glow, lambda v: int(v * (0.7 + 0.3 * pulse)))
        dust3.step(dt)
        dust3.draw(d)
        layers = [fig, fx]

    _last["t"] = t
    # composite: golden glow, figure, fx
    gl = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.composite(Image.new("RGB", (W, H), GOLD), img, gl.point(lambda v: int(v * 0.8)))
    img = img.convert("RGBA")
    for L in layers:
        img.alpha_composite(L)
    img = img.convert("RGB")
    if flash > 0:
        img = Image.blend(img, Image.new("RGB", (W, H), (255, 236, 200)), clamp(flash))
    if shake > 0:
        dx, dy = rnd.uniform(-shake, shake), rnd.uniform(-shake, shake)
        img = img.transform((W, H), Image.AFFINE, (1, 0, dx, 0, 1, dy), fillcolor=(0, 0, 0))
    return np.asarray(img)


def fast(t):
    return 1.4 < t < 3.4 or 5.2 < t < 6.1 or 8.3 < t < 9.0


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)],
        stdin=subprocess.PIPE,
    )
    n = int(DUR * FPS)
    for i in range(n):
        t = i / FPS
        f = frame(t).astype(np.float32)
        if fast(t):  # cheap motion blur: blend a sub-frame from half a frame back
            f = 0.5 * f + 0.5 * frame(t - 0.5 / FPS).astype(np.float32)
            _last["t"] = t
        ff.stdin.write(f.astype(np.uint8).tobytes())
    ff.stdin.close()
    ff.wait()
    print(OUT)


if __name__ == "__main__":
    main()
