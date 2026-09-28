#!/usr/bin/env python3
"""
PVideo cartoon engine — FREE animated video generator.
Text script -> vertical (9:16) MP4 with voiceover + captions +
FRAME-BY-FRAME 2D cartoon animation with STORY-DRIVEN movement:
walk cycles, reaching, eating, jumping, talking mouths, facial
expressions, props, multiple characters.

Modes:
  * generic (default): each scene animates the boy — walking across the
    screen, jumping with joy, sitting under the night sky.
  * --story samosa: scripted 3-beat story "Golu aur Jadui Samose":
    1. Golu walks out of his house to the market (walk cycle, butterflies)
    2. The shopkeeper greets him and hands over a hot samosa (two
       characters interacting, talking mouths)
    3. He eats it -> magic sparkles + confetti -> jumps with joy

Pipeline: scenes -> TTS/voice file -> per-beat durations -> 24fps PIL
frames piped to ffmpeg -> H.264 + AAC, yuv420p, 1080x1920, +faststart
(WhatsApp / YouTube Shorts compatible). stdlib + PIL + ffmpeg only.
"""
import argparse
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

# reuse the battle-tested bits (scene split, TTS chain, fonts, durations)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_video as base

W, H = 1080, 1920
FPS = 24

# ---------------------------------------------------------------- palette
SKIN = (255, 217, 179)
HAIR = (59, 42, 32)
SHIRT = (255, 140, 66)
PANTS = (63, 120, 200)
CHEEK = (255, 150, 150)
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)

NIGHT_WORDS = ["चाँद", "चांद", "चाँदनी", "रात", "तारा", "तारे", "सितारा",
               "moon", "night", "star", "सो जा", "नींद", "आसमान"]


# ---------------------------------------------------------------- fonts
# Self-contained: bundled Devanagari font FIRST (does not depend on
# make_video.py's find_font — works even if that file is outdated).
def find_font():
    """Bold font that covers Devanagari + Latin (for Hindi/English captions)."""
    import glob
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    cands = sorted(glob.glob(os.path.join(here, "*.ttf")))
    try:
        r = subprocess.run(
            ["fc-match", "Noto Sans Devanagari:weight=bold", "--format", "%{file}"],
            capture_output=True, text=True, timeout=15)
        p = r.stdout.strip()
        if p.endswith(".ttf") and os.path.exists(p):
            cands.append(p)
    except Exception:
        pass
    cands += ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for c in cands:
        if os.path.exists(c):
            return c
    raise RuntimeError("No TTF font found (system or engine/fonts/)")


def scene_kind(text):
    tl = text.lower()
    return "night" if any(w in text or w in tl for w in NIGHT_WORDS) else "day"


# ---------------------------------------------------------------- helpers
def vgrad(img, top, bottom):
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)


def limb(d, x1, y1, ang_deg, length, width, color):
    """Limb from pivot (x1,y1); 0deg = straight down, + = swings right."""
    a = math.radians(ang_deg)
    x2 = x1 + length * math.sin(a)
    y2 = y1 + length * math.cos(a)
    d.line([(x1, y1), (x2, y2)], fill=color, width=int(width))
    d.ellipse([x2 - width / 2, y2 - width / 2,
               x2 + width / 2, y2 + width / 2], fill=color)
    return x2, y2


def star4(d, x, y, r, color):
    k = 0.28
    d.polygon([(x, y - r), (x + r * k, y - r * k), (x + r, y),
               (x + r * k, y + r * k), (x, y + r), (x - r * k, y + r * k),
               (x - r, y), (x - r * k, y - r * k)], fill=color)


def cloud(d, cx, cy, s, color):
    d.ellipse([cx - 95 * s, cy - 32 * s, cx + 95 * s, cy + 32 * s], fill=color)
    d.ellipse([cx - 55 * s, cy - 58 * s, cx + 55 * s, cy + 6 * s], fill=color)
    d.ellipse([cx + 5 * s, cy - 50 * s, cx + 105 * s, cy + 14 * s], fill=color)


def tree(d, bx, by, s):
    d.rounded_rectangle([bx - 42 * s, by - 260 * s, bx + 42 * s, by + 10 * s],
                        radius=int(30 * s), fill=(107, 66, 38))
    for ox, oy, r, col in [ (0, -330, 130, (45, 106, 79)),
                            (-95, -260, 88, (64, 145, 108)),
                            (95, -260, 92, (52, 125, 92)) ]:
        d.ellipse([bx + (ox - r) * s, by + (oy - r) * s,
                   bx + (ox + r) * s, by + (oy + r) * s], fill=col)


def hills(d, c1, c2):
    d.ellipse([-450, 1360, 950, 2150], fill=c1)
    d.ellipse([350, 1430, 1560, 2180], fill=c2)


# ---------------------------------------------------------------- character
def face(d, hx, hy, r, s, mood, blink, hair=HAIR, look_up=False,
         talk=False, t=0):
    """Cute face with expressions + talking mouth. mood: happy|surprised|neutral."""
    d.ellipse([hx - r, hy - r - 26 * s, hx + r, hy + r - 26 * s], fill=hair)
    d.ellipse([hx - r * 0.96, hy - r * 0.86, hx + r * 0.96, hy + r * 0.96],
              fill=SKIN)
    # fringe
    d.ellipse([hx - r * 0.96, hy - r * 1.02, hx + r * 0.96,
               hy - r * 0.30], fill=hair)
    ex, ey = r * 0.36, -r * 0.05
    for sx in (-1, 1):
        cxp = hx + sx * ex
        cyp = hy + ey + (-10 * s if look_up else 0)
        if blink:
            d.line([(cxp - 15 * s, cyp), (cxp + 15 * s, cyp)],
                   fill=BLACK, width=int(6 * s))
        elif mood == "happy":
            # closed happy eyes
            d.arc([cxp - 16 * s, cyp - 14 * s, cxp + 16 * s, cyp + 14 * s],
                  start=180, end=360, fill=BLACK, width=int(7 * s))
        elif mood == "surprised":
            d.ellipse([cxp - 19 * s, cyp - 20 * s,
                       cxp + 19 * s, cyp + 20 * s], fill=WHITE)
            d.ellipse([cxp - 9 * s, cyp - 9 * s,
                       cxp + 9 * s, cyp + 9 * s], fill=BLACK)
        else:
            d.ellipse([cxp - 16 * s, cyp - 15 * s,
                       cxp + 16 * s, cyp + 15 * s], fill=WHITE)
            d.ellipse([cxp - 7 * s, cyp - 7 * s,
                       cxp + 7 * s, cyp + 7 * s], fill=BLACK)
        d.ellipse([cxp + sx * 30 * s - 12 * s, hy + r * 0.32 - 9 * s,
                   cxp + sx * 30 * s + 12 * s, hy + r * 0.32 + 9 * s],
                  fill=CHEEK)
    if talk and not blink:
        # talking mouth: opens and closes
        op = abs(math.sin(2 * math.pi * 3.4 * t + hx * 0.01))
        mh = r * (0.16 + 0.32 * op)
        d.ellipse([hx - 22 * s, hy + r * 0.28,
                   hx + 22 * s, hy + r * 0.28 + mh], fill=(130, 45, 45))
        d.rectangle([hx - 22 * s, hy + r * 0.28,
                     hx + 22 * s, hy + r * 0.28 + mh * 0.35],
                    fill=(255, 255, 255))
    elif mood == "surprised":
        d.ellipse([hx - 15 * s, hy + r * 0.28, hx + 15 * s, hy + r * 0.58],
                  fill=(120, 40, 40))
    elif mood == "happy":
        d.arc([hx - 38 * s, hy + r * 0.12, hx + 38 * s, hy + r * 0.66],
              start=25, end=155, fill=BLACK, width=int(8 * s))
    else:
        d.arc([hx - 30 * s, hy + r * 0.18, hx + 30 * s, hy + r * 0.62],
              start=25, end=155, fill=BLACK, width=int(6 * s))


def draw_boy(d, x, yb, s, t, action="idle", mood="happy", facing=1,
             hand_prop=None, shirt=SHIRT, pants=PANTS, hair=HAIR,
             talk=False, cap=None):
    """Chibi character with real story motion. yb = ground (feet) y.

    action: idle | walk | reach | eat | jump | wave | sit
    mood: happy | surprised | neutral
    facing: 1 (right) | -1 (left)
    hand_prop: None | "samosa" (drawn in the leading hand)
    shirt/pants/hair: recolor for extra characters; cap: cap color or None
    talk: talking mouth animation
    """
    blink = (t % 3.4) < 0.13
    f = facing

    # ---- pose solve (angles; 0deg = down, + = toward facing side) ----
    legL = legR = 0.0
    arm_lead = arm_trail = 0.0
    lean = 0.0
    bob = 0.0
    jump = 0.0

    if action == "walk":
        # full walk cycle: legs alternate, arms swing opposite, body bobs
        ph = 2 * math.pi * 1.5 * t
        legL = 34 * math.sin(ph) * f
        legR = 34 * math.sin(ph + math.pi) * f
        arm_lead = (10 + 24 * math.sin(ph)) * f
        arm_trail = (10 + 24 * math.sin(ph + math.pi)) * f
        bob = 12 * s * abs(math.cos(ph))
        lean = 10 * f
    elif action == "reach":
        # arm stretches toward the facing side, reaching in and out
        arm_lead = (64 + 24 * math.sin(2 * math.pi * 0.9 * t)) * f
        arm_trail = 12 * f
        legL, legR = 10 * f, -10 * f
        lean = 16 * f
        bob = 4 * s * math.sin(2 * math.pi * 0.9 * t)
    elif action == "eat":
        # hand travels to the mouth again and again
        arm_lead = (72 + 58 * math.sin(2 * math.pi * 1.15 * t)) * f
        arm_trail = 12 * f
        bob = 5 * s * math.sin(2 * math.pi * 1.15 * t + 1)
        lean = 6 * f
    elif action == "jump":
        jump = 105 * s * abs(math.sin(math.pi * 1.35 * t))
        arm_lead, arm_trail = 150 * f, -150 * f
        legL, legR = 14 * f, -14 * f
    elif action == "wave":
        arm_lead = (125 + 28 * math.sin(2 * math.pi * 2.1 * t)) * f
        arm_trail = 12 * f
        bob = 8 * s * abs(math.sin(math.pi * 1.1 * t))
    elif action == "sit":
        # calm folded-legs pose (night)
        for sx in (-1, 1):
            d.ellipse([x + sx * 118 * s - 55 * s, yb - 58 * s,
                       x + sx * 118 * s + 55 * s, yb + 8 * s], fill=pants)
        d.rounded_rectangle([x - 54 * s, yb - 155 * s, x + 54 * s, yb - 8 * s],
                            radius=int(26 * s), fill=shirt)
        limb(d, x - 50 * s, yb - 130 * s, 18, 95 * s, 26 * s, SKIN)
        limb(d, x + 50 * s, yb - 130 * s, -18, 95 * s, 26 * s, SKIN)
        face(d, x + 6 * s, yb - 235 * s, 80 * s, s, mood, blink,
             hair=hair, look_up=True, talk=talk, t=t)
        return
    else:  # idle
        arm_lead, arm_trail = 12 * f, -12 * f
        bob = 6 * s * math.sin(2 * math.pi * 0.7 * t)

    yb_e = yb - bob - jump
    hip = yb_e - 165 * s
    shy = yb_e - 300 * s

    # shadow (shrinks while jumping)
    sh_scale = max(0.45, 1 - jump / (320 * s))
    d.ellipse([x - 95 * s * sh_scale, yb + 4,
               x + 95 * s * sh_scale, yb + 30], fill=(0, 0, 0, 90))

    # legs + shoes
    for hx, ang in ((x - 32 * s + lean, legL), (x + 32 * s + lean, legR)):
        fx, fy = limb(d, hx, hip, ang, 160 * s, 30 * s, pants)
        d.ellipse([fx - 30 * s, fy - 16 * s,
                   fx + 30 * s, fy + 14 * s], fill=(60, 40, 30))

    # torso
    d.rounded_rectangle([x - 56 * s + lean, yb_e - 335 * s,
                         x + 56 * s + lean, yb_e - 155 * s],
                        radius=int(28 * s), fill=shirt)
    d.arc([x - 24 * s + lean, yb_e - 335 * s,
           x + 24 * s + lean, yb_e - 295 * s],
          start=25, end=155, fill=(230, 110, 50), width=int(8 * s))

    # arms (lead arm = the one on the facing side)
    limb(d, x - 52 * s * f + lean, shy, arm_trail, 110 * s, 26 * s, SKIN)
    lhx, lhy = limb(d, x + 52 * s * f + lean, shy, arm_lead,
                    110 * s, 26 * s, SKIN)

    # head
    hxc, hyc = x + lean + 6 * f * s, yb_e - 415 * s
    face(d, hxc, hyc, 80 * s, s, mood, blink, hair=hair, talk=talk, t=t)
    if cap:
        d.ellipse([hxc - 48 * s, hyc - 80 * s - 44 * s,
                   hxc + 48 * s, hyc - 80 * s + 6 * s], fill=cap)

    # prop in the leading hand
    if hand_prop == "samosa":
        draw_samosa(d, lhx, lhy - 10 * s, 0.8 * s)


# ---------------------------------------------------------------- props
def draw_samosa(d, x, y, s):
    pts = [(x, y - 42 * s), (x - 38 * s, y + 28 * s), (x + 38 * s, y + 28 * s)]
    d.polygon(pts, fill=(226, 158, 62), outline=(176, 116, 40))
    d.line([(x - 14 * s, y - 12 * s), (x + 10 * s, y + 16 * s)],
           fill=(240, 190, 110), width=int(8 * s))


def draw_shop_back(d, bx, by, s, sign_font):
    """Shop back wall + striped awning + sign (character goes in front)."""
    d.rounded_rectangle([bx - 280 * s, by - 560 * s, bx + 280 * s, by - 200 * s],
                        radius=18, fill=(255, 248, 235))
    for i in range(8):
        x0 = bx - 320 * s + i * 80 * s
        col = (214, 64, 64) if i % 2 == 0 else (255, 246, 238)
        d.polygon([(x0, by - 560 * s), (x0 + 80 * s, by - 560 * s),
                   (x0 + 58 * s, by - 680 * s), (x0 - 22 * s, by - 680 * s)],
                  fill=col)
    d.rounded_rectangle([bx - 330 * s, by - 700 * s, bx + 330 * s, by - 668 * s],
                        radius=10, fill=(178, 52, 52))
    d.rounded_rectangle([bx - 170 * s, by - 660 * s, bx + 170 * s, by - 580 * s],
                        radius=16, fill=(255, 252, 240), outline=(178, 52, 52))
    d.text((bx, by - 620 * s), "गरम समोसे", font=sign_font,
           anchor="mm", fill=(170, 40, 40))


def draw_shop_front(d, bx, by, s, t):
    """Counter + samosa tray (drawn in front of the shopkeeper)."""
    d.rounded_rectangle([bx - 260 * s, by - 240 * s, bx + 260 * s, by],
                        radius=16, fill=(146, 98, 58))
    d.rectangle([bx - 260 * s, by - 240 * s, bx + 260 * s, by - 214 * s],
                fill=(120, 78, 44))
    d.ellipse([bx - 200 * s, by - 300 * s, bx + 200 * s, by - 216 * s],
              fill=(205, 205, 205))
    d.ellipse([bx - 200 * s, by - 300 * s, bx + 200 * s, by - 262 * s],
              fill=(232, 232, 232))
    for i, sx in enumerate((-120, 0, 120)):
        draw_samosa(d, bx + sx * s,
                    by - 330 * s + 7 * s * math.sin(2 * math.pi * 1.1 * t + i * 2.1),
                    0.85 * s)


def draw_sparkles(d, cx, cy, t, n=16, spread=300, seed=7):
    """Magic sparkle burst: twinkling stars drifting upward."""
    rnd = random.Random(seed)
    for _ in range(n):
        ox = rnd.uniform(-spread, spread)
        oy = rnd.uniform(-spread * 0.8, spread * 0.8)
        ph = rnd.uniform(0, 6.283)
        r0 = rnd.uniform(9, 24)
        r = r0 * (0.35 + 0.65 * abs(math.sin(2 * math.pi * 1.7 * t + ph)))
        rise = (t * 70 + rnd.uniform(0, 200)) % 220
        if r > 2:
            star4(d, cx + ox, cy + oy - rise * 0.4, r, (255, 243, 170))


def draw_confetti(d, t, seed=21, n=42):
    """Celebration confetti falling from the top."""
    rnd = random.Random(seed)
    cols = [(255, 100, 100), (100, 200, 255), (255, 220, 100),
            (150, 255, 150), (220, 150, 255)]
    for i in range(n):
        x0 = rnd.uniform(0, W)
        y = (rnd.uniform(0, H) + t * 260) % (H + 100) - 50
        x = x0 + 40 * math.sin(2 * math.pi * 0.8 * t + i)
        c = cols[i % len(cols)]
        d.rectangle([x - 9, y - 6, x + 9, y + 6], fill=c)


def draw_house(d, bx, by, s):
    """Simple storybook house (by = ground)."""
    d.rectangle([bx - 170 * s, by - 260 * s, bx + 170 * s, by],
                fill=(255, 243, 224))
    d.polygon([(bx - 210 * s, by - 250 * s), (bx + 210 * s, by - 250 * s),
               (bx, by - 420 * s)], fill=(200, 90, 70))
    d.rectangle([bx - 50 * s, by - 160 * s, bx + 50 * s, by],
                fill=(140, 95, 60))
    d.rectangle([bx - 140 * s, by - 220 * s, bx - 70 * s, by - 150 * s],
                fill=(170, 210, 240))
    d.rectangle([bx + 70 * s, by - 220 * s, bx + 140 * s, by - 150 * s],
                fill=(170, 210, 240))


def draw_butterfly(d, t, seed):
    """Wandering butterfly with flapping wings."""
    rnd = random.Random(seed)
    bx0, by0 = rnd.uniform(120, 920), rnd.uniform(950, 1250)
    bx = bx0 + 130 * math.sin(2 * math.pi * 0.23 * t + seed)
    by = by0 + 70 * math.sin(2 * math.pi * 0.41 * t + seed * 2)
    flap = abs(math.sin(2 * math.pi * 6 * t + seed))
    w = 5 + 17 * flap
    for sx in (-1, 1):
        x0, x1 = bx + sx * 3, bx + sx * 27
        d.ellipse([min(x0, x1), by - w, max(x0, x1), by + w],
                  fill=(255, 150, 200))
    d.ellipse([bx - 5, by - 11, bx + 5, by + 11], fill=(80, 50, 40))


# ---------------------------------------------------------------- static scene layers
def has_devanagari(text):
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def fit_caption(text, font_path):
    tmp_img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(tmp_img)
    try:
        layout = ImageFont.Layout.RAQM
    except AttributeError:
        layout = None
    size = 76
    while size >= 34:
        kw = {"layout_engine": layout} if layout else {}
        font = ImageFont.truetype(font_path, size, **kw)
        words, lines, cur = text.split(), [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if d.textlength(t, font=font) <= W - 220:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        wrapped = "\n".join(lines)
        bb = d.multiline_textbbox((0, 0), wrapped, font=font, stroke_width=2)
        if bb[3] - bb[1] <= 380:
            return font, wrapped
        size -= 6
    return font, wrapped


def static_layer(kind, scene_text, idx, n_scenes, title, font_path, latin_font):
    img = Image.new("RGB", (W, H))
    d0 = ImageDraw.Draw(img)
    if kind == "night":
        vgrad(img, (11, 16, 38), (32, 52, 92))
        hills(d0, (18, 58, 36), (13, 44, 28))
        tree(d0, 250, 1520, 1.0)
    else:
        vgrad(img, (110, 190, 245), (214, 243, 255))
        hills(d0, (87, 167, 115), (62, 142, 90))
        tree(d0, 230, 1520, 1.0)
        # flowers (stems static; heads sway per-frame)
        for i, fx in enumerate([180, 420, 700, 880, 1020]):
            d0.line([(fx, 1780), (fx, 1660)], fill=(46, 125, 50), width=8)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((70, 90), "PVideo", font=ImageFont.truetype(latin_font, 44),
           fill=(255, 255, 255, 200))
    # caption box + text (Devanagari font lacks Latin glyphs -> pick per text)
    cap_text = base.strip_emoji(scene_text)
    cap_font_path = font_path if has_devanagari(cap_text) else latin_font
    font, wrapped = fit_caption(cap_text, cap_font_path)
    bb = d.multiline_textbbox((0, 0), wrapped, font=font, stroke_width=2)
    th = bb[3] - bb[1]
    box_top = 560
    d.rounded_rectangle([70, box_top - 36, W - 70, box_top + th + 36],
                        radius=28, fill=(0, 0, 0, 150))
    if title and idx == 0:
        try:
            layout = ImageFont.Layout.RAQM
        except AttributeError:
            layout = None
        kw = {"layout_engine": layout} if layout else {}
        title_text = base.strip_emoji(title)
        title_font_path = font_path if has_devanagari(title_text) else latin_font
        d.text((W // 2, box_top - 120), title_text,
               font=ImageFont.truetype(title_font_path, 60, **kw),
               anchor="ma", fill=(255, 214, 90))
    d.multiline_text((W // 2, box_top), wrapped, font=font, anchor="ma",
                     align="center", fill="white", stroke_width=2,
                     stroke_fill=(0, 0, 0))
    # progress bar
    bar_w = int(W * (idx + 1) / n_scenes)
    d.rectangle([0, H - 24, W, H], fill=(0, 0, 0, 160))
    d.rectangle([0, H - 24, bar_w, H], fill=(255, 214, 90))
    return img


# ---------------------------------------------------------------- per-frame dynamic drawing
def day_background(d, t, seed):
    """Sun, drifting clouds, flapping birds, butterflies, swaying flowers."""
    # sun with slowly rotating rays + face
    sx, sy, sr = 830, 300, 95
    for i in range(12):
        a = math.radians(i * 30 + t * 18)
        x1, y1 = sx + (sr + 18) * math.cos(a), sy + (sr + 18) * math.sin(a)
        x2, y2 = sx + (sr + 58) * math.cos(a), sy + (sr + 58) * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=(255, 200, 60), width=12)
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(255, 221, 68))
    for ex in (-32, 32):
        d.ellipse([sx + ex - 11, sy - 14, sx + ex + 11, sy + 14], fill=BLACK)
    d.arc([sx - 34, sy + 12, sx + 34, sy + 56], start=25, end=155,
          fill=BLACK, width=6)
    # drifting clouds
    for i, (y0, s, v) in enumerate([(480, 1.2, 26), (650, 0.9, 38), (380, 1.4, 18)]):
        cx = ((seed * 211 + i * 430 + v * t) % (W + 520)) - 260
        cloud(d, cx, y0, s, WHITE)
    # birds flapping across the sky
    for i in range(3):
        bx = ((seed * 97 + i * 380 + 55 * t) % (W + 300)) - 150
        by = 560 + i * 90 + 24 * math.sin(2 * math.pi * 0.7 * t + i * 2)
        flap = math.sin(2 * math.pi * 5 * t + i)
        wsp = 34 * (0.55 + 0.45 * abs(flap))
        d.arc([bx - wsp, by - 14, bx, by + 14], start=195, end=345,
              fill=BLACK, width=7)
        d.arc([bx, by - 14, bx + wsp, by + 14], start=195, end=345,
              fill=BLACK, width=7)
    # butterflies
    draw_butterfly(d, t, seed + 5)
    draw_butterfly(d, t * 1.13 + 40, seed + 9)
    # swaying flower heads
    for i, fx in enumerate([180, 420, 700, 880, 1020]):
        sway = 7 * math.sin(2 * math.pi * 0.9 * t + i * 1.7)
        d.ellipse([fx - 20 + sway, 1620, fx + 20 + sway, 1660],
                  fill=(255, 120, 150) if i % 2 else (255, 200, 80))


def draw_frame(base_img, kind, t, seed, dur, idx):
    """Generic mode: the boy WALKs across every day scene (real movement),
    jumps with joy every third scene, sits under the night sky at night."""
    img = base_img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    rnd = random.Random(seed)
    if kind == "night":
        # twinkling stars (twinkle by size)
        for _ in range(75):
            sx, sy = rnd.randint(0, W), rnd.randint(0, 1280)
            r0 = rnd.uniform(4, 11)
            ph = rnd.uniform(0, 6.28)
            r = r0 * (0.55 + 0.45 * math.sin(2 * math.pi * 1.4 * t + ph))
            if r > 1:
                star4(d, sx, sy, r, (255, 255, 230))
        # moon with happy sleepy face, gentle bob
        mx, my = 830, 300 + 12 * math.sin(2 * math.pi * 0.35 * t)
        d.ellipse([mx - 105, my - 105, mx + 105, my + 105], fill=(245, 240, 220))
        for cx, cy, cr in [(-40, -30, 22), (30, 20, 16), (-5, 55, 12)]:
            d.ellipse([mx + cx - cr, my + cy - cr, mx + cx + cr, my + cy + cr],
                      fill=(227, 220, 192))
        d.arc([mx - 45, my - 25, mx - 5, my + 15], start=200, end=340,
              fill=(90, 90, 90), width=6)
        d.arc([mx + 5, my - 25, mx + 45, my + 15], start=200, end=340,
              fill=(90, 90, 90), width=6)
        d.arc([mx - 28, my + 18, mx + 28, my + 58], start=25, end=155,
              fill=(90, 90, 90), width=6)
        # drifting clouds
        for i, (y0, s, v) in enumerate([(520, 1.1, 22), (680, 0.8, 34), (430, 1.3, 15)]):
            cx = ((seed * 137 + i * 420 + v * t) % (W + 520)) - 260
            cloud(d, cx, y0, s, (221, 230, 240))
        # child sitting under tree, gazing up at the moon
        draw_boy(d, 660, 1560, 1.12, t, action="sit", mood="neutral")
    else:
        day_background(d, t, seed)
        if idx % 3 == 2:
            # celebration scene: jumping with joy at center
            draw_boy(d, W / 2, 1600, 1.12, t, action="jump",
                     mood="happy", facing=1)
        else:
            # walk across the whole screen during the scene
            x = 140 + (W - 280) * min(t / dur, 1.0)
            draw_boy(d, x, 1600, 1.12, t, action="walk",
                     mood="happy", facing=1)
    return img


# ---------------------------------------------------------------- story mode: Golu aur Jadui Samose
# (caption, narration) per beat — durations scale with narration length.
STORY_SAMOSA = [
    ("गोलू घर से बाजार चला।",
     "गोलू खुशी-खुशी अपने घर से बाजार की तरफ चला। "
     "रास्ते में रंग-बिरंगी तितलियाँ उड़ रही थीं।"),
    ("दुकानदार ने समोसा दिया।",
     "दुकान पर गरम-गरम समोसे सजे थे। दुकानदार बोला — अरे गोलू, "
     "गरम समोसा ले! गोलू ने हाथ बढ़ाकर समोसा ले लिया।"),
    ("जादुई चमक! गोलू खुश हुआ।",
     "जैसे ही उसने समोसा खाया, चारों तरफ जादुई चमक फैल गई। "
     "गोलू खुशी से उछल पड़ा और बोला — वाह, जादुई समोसा!"),
]

# shopkeeper look
KEEPER_SHIRT = (58, 140, 95)
KEEPER_PANTS = (90, 70, 50)
KEEPER_CAP = (245, 245, 240)


def story_frame(base_img, beat, t, dur, seed, sign_font):
    img = base_img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    if beat == 0:
        # beat 1: Golu leaves home and WALKS to the market
        day_background(d, t, seed)
        draw_house(d, 880, 1560, 1.0)
        x = 140 + (W - 280) * min(t / dur, 1.0)
        draw_boy(d, x, 1600, 1.12, t, action="walk", mood="happy", facing=1)
    elif beat == 1:
        # beat 2: the shopkeeper greets Golu and HANDS him a samosa
        day_background(d, t, seed)
        draw_shop_back(d, 780, 1620, 1.0, sign_font)
        give = 0.25 * dur < t < 0.65 * dur
        keeper_act = "reach" if give else "idle"
        keeper_prop = "samosa" if 0.25 * dur < t < 0.52 * dur else None
        draw_boy(d, 780, 1620, 1.18, t, action=keeper_act, mood="happy",
                 facing=-1, hand_prop=keeper_prop, shirt=KEEPER_SHIRT,
                 pants=KEEPER_PANTS, talk=give, cap=KEEPER_CAP)
        draw_shop_front(d, 780, 1620, 1.0, t)
        # Golu reaches out and takes it
        golu_prop = "samosa" if t > dur * 0.45 else None
        draw_boy(d, 400, 1600, 1.12, t, action="reach", mood="happy",
                 facing=1, hand_prop=golu_prop)
    else:
        # beat 3: he EATS -> magic sparkles + confetti -> JUMPS with joy
        day_background(d, t, seed)
        if t < dur * 0.55:
            draw_boy(d, 540, 1600, 1.12, t, action="eat", mood="happy",
                     facing=1, hand_prop="samosa")
        else:
            draw_confetti(d, t - dur * 0.55, seed=21)
            draw_sparkles(d, 540, 1050, t - dur * 0.55, n=18, spread=320,
                          seed=11)
            golu_talk = t > dur - 1.4
            draw_boy(d, 540, 1600, 1.12, t, action="jump", mood="happy",
                     facing=1, talk=golu_talk)
    return img


def render_story(out_mp4, title, font_path, latin_font, tmp, voice_mp3,
                 story="samosa"):
    beats = STORY_SAMOSA if story == "samosa" else None
    if not beats:
        sys.exit(f"Unknown story: {story}")
    n = len(beats)
    total = base.media_duration(voice_mp3)
    durs = base.scene_durations([nar for _, nar in beats], total)
    print(f"[cartoon] story beats: {[f'{x:.1f}s' for x in durs]}", flush=True)
    statics = [static_layer("day", cap, i, n, title, font_path, latin_font)
               for i, (cap, _) in enumerate(beats)]
    try:
        sign_font = ImageFont.truetype(font_path, 54)
    except Exception:
        sign_font = ImageFont.load_default()

    vonly = os.path.join(tmp, "video_nosound.mp4")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", vonly],
        stdin=subprocess.PIPE)
    total_frames = 0
    for i, (st, dur) in enumerate(zip(statics, durs)):
        nfr = max(int(round(dur * FPS)), FPS // 2)
        for fr in range(nfr):
            t = fr / FPS
            frame = story_frame(st, i, t, dur, 1000 + i, sign_font)
            ff.stdin.write(frame.tobytes())
        total_frames += nfr
        print(f"[cartoon] beat {i + 1}/{n} ({dur:.1f}s)", flush=True)
    ff.stdin.close()
    ff.wait()
    if ff.returncode != 0:
        raise RuntimeError("ffmpeg frame pipe failed")
    print(f"[cartoon] frames: {total_frames}", flush=True)
    return vonly


# ---------------------------------------------------------------- render (generic mode)
def render_cartoon(out_mp4, scenes, durs, title, font_path, latin_font, tmp):
    kinds = [scene_kind(s) for s in scenes]
    print(f"[cartoon] scene kinds: {kinds}", flush=True)
    statics = [static_layer(k, s, i, len(scenes), title, font_path, latin_font)
               for i, (k, s) in enumerate(zip(kinds, scenes))]

    vonly = os.path.join(tmp, "video_nosound.mp4")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", vonly],
        stdin=subprocess.PIPE)
    total_frames = 0
    for i, (st, dur, k) in enumerate(zip(statics, durs, kinds)):
        nfr = max(int(round(dur * FPS)), FPS // 2)
        for fr in range(nfr):
            t = fr / FPS
            frame = draw_frame(st, k, t, 1000 + i, dur, i)
            ff.stdin.write(frame.tobytes())
        total_frames += nfr
        print(f"[cartoon] scene {i + 1}/{len(scenes)} ({dur:.1f}s, {k})",
              flush=True)
    ff.stdin.close()
    ff.wait()
    if ff.returncode != 0:
        raise RuntimeError("ffmpeg frame pipe failed")
    print(f"[cartoon] frames: {total_frames}", flush=True)
    return vonly


def mux(vonly, voice_mp3, out_mp4):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", vonly, "-i", voice_mp3,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-shortest", "-movflags", "+faststart", out_mp4], check=True)


def main():
    ap = argparse.ArgumentParser(description="PVideo cartoon engine — animated video")
    ap.add_argument("--text", required=False, default="")
    ap.add_argument("--lang", default="hi", choices=["hi", "en"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--tts", default=None, choices=["edge-tts", "gtts", "espeak"])
    ap.add_argument("--voice-file", default=None,
                    help="Use this MP3 as the voiceover instead of TTS")
    ap.add_argument("--story", default=None, choices=["samosa"],
                    help="Scripted story mode with story-driven animation")
    ap.add_argument("--keep-temp", action="store_true")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="pvideo_cartoon_")
    try:
        font = find_font()
        latin_font = base.find_latin_font()
        print(f"[cartoon] font: {os.path.basename(font)}", flush=True)

        if a.story:
            beats = STORY_SAMOSA
            narration = " ".join(nar for _, nar in beats)
            voice = os.path.join(tmp, "voice.mp3")
            if a.voice_file:
                shutil.copy(a.voice_file, voice)
                provider = "custom"
            else:
                provider = base.make_voiceover(narration, a.lang, voice,
                                               prefer=a.tts)
            total = base.media_duration(voice)
            print(f"[cartoon] TTS: {provider}, audio {total:.1f}s", flush=True)
            vonly = render_story(a.out, a.title, font, latin_font, tmp, voice,
                                 story=a.story)
        else:
            scenes = base.split_scenes(a.text)
            if not scenes:
                sys.exit("No scenes: empty text")
            print(f"[cartoon] scenes: {len(scenes)}", flush=True)
            voice = os.path.join(tmp, "voice.mp3")
            if a.voice_file:
                shutil.copy(a.voice_file, voice)
                provider = "custom"
            else:
                provider = base.make_voiceover(a.text, a.lang, voice,
                                               prefer=a.tts)
            total = base.media_duration(voice)
            print(f"[cartoon] TTS: {provider}, audio {total:.1f}s", flush=True)
            durs = base.scene_durations(scenes, total)
            vonly = render_cartoon(a.out, scenes, durs, a.title, font,
                                   latin_font, tmp)

        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        mux(vonly, voice, a.out)
        print(f"[cartoon] DONE -> {a.out}")
    finally:
        if not a.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
