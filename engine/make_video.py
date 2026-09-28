#!/usr/bin/env python3
"""
PVideo v1 engine — FREE video generator.
Text script -> vertical (9:16) MP4 with voiceover + captions.

Pipeline:
  1. Split script into scenes (sentence-based, ~90 chars max).
  2. TTS: try edge-tts (free, no key); fall back to gTTS (free, no key);
     final fallback espeak-ng (fully local, no network).
  3. One MP3 for the whole script -> total duration via ffprobe ->
     scene durations distributed proportionally by character count
     (approximation: assumes uniform speaking rate; min 1.8s/scene).
  4. PIL renders one 1080x1920 caption card per scene (Devanagari-safe
     via RAQM/harfbuzz shaping, gradient backgrounds, progress bar).
  5. ffmpeg: per-scene slow zoom (zoompan) -> concat -> mux AAC audio.
     Output: H.264 + AAC, yuv420p, 1080x1920, 30fps, +faststart
     (WhatsApp / YouTube Shorts compatible).

RAM: only stdlib + PIL + ffmpeg CLI. No heavy frameworks (2GB VPS safe).
"""
import argparse
import asyncio
import colorsys
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
MIN_SCENE_S = 1.8

VOICES = {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"}
ESPEAK_VOICES = {"hi": "hi", "en": "en"}


# ---------------------------------------------------------------- fonts
def find_font():
    """Bold font that covers Devanagari + Latin (for Hindi/English captions)."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    # Bundled engine font FIRST — guaranteed Devanagari coverage.
    # (fc-match silently falls back to a Latin-only font like DejaVu when
    # Noto Sans Devanagari is not installed, which renders Hindi as tofu.)
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


def find_latin_font():
    """Bold Latin font (watermark/brand text — Devanagari fonts may lack Latin)."""
    try:
        r = subprocess.run(
            ["fc-match", "DejaVu Sans:weight=bold", "--format", "%{file}"],
            capture_output=True, text=True, timeout=15)
        p = r.stdout.strip()
        if p.endswith(".ttf") and os.path.exists(p):
            return p
    except Exception:
        pass
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ---------------------------------------------------------------- scenes
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE00-\uFE0F\u200D"
    "\u2190-\u21FF\u2300-\u23FF\U0001F1E6-\U0001F1FF]",
    flags=re.UNICODE)


def strip_emoji(text):
    """Remove emoji/symbols (no color-emoji font on server); TTS text untouched."""

def scene_durations(scenes, total):
    """Distribute total audio seconds across scenes, proportional to characters.

    Approximation: assumes the TTS speaks every character at roughly the same
    rate. Short scenes get a floor of MIN_SCENE_S so captions stay readable.
    """
    n = len(scenes)
    weights = [max(len(s), 1) for s in scenes]
    floor_total = MIN_SCENE_S * n
    if total <= floor_total:
        return [total / n] * n
    rest = total - floor_total
    wsum = sum(weights)
    return [MIN_SCENE_S + rest * w / wsum for w in weights]


# ---------------------------------------------------------------- TTS
async def _edge_save(text, voice, out):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(out)


def tts_edge(text, lang, out):
    async def run():
        await asyncio.wait_for(
            _edge_save(text, VOICES[lang], out), timeout=120)
    asyncio.run(run())


def tts_gtts(text, lang, out):
    from gtts import gTTS
    try:
        gTTS(text=text, lang=lang, tld="co.in", slow=False).save(out)
    except Exception:
        # very long text: split in halves and stitch
        mid = len(text) // 2
        cut = text.rfind(" ", 0, mid)
        cut = cut if cut > 0 else mid
        p1, p2 = out + ".a.mp3", out + ".b.mp3"
        gTTS(text=text[:cut], lang=lang, tld="co.in", slow=False).save(p1)
        gTTS(text=text[cut:], lang=lang, tld="co.in", slow=False).save(p2)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", p1, "-i", p2,
             "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
             "-c:a", "libmp3lame", out], check=True)


def tts_espeak(text, lang, out):
    """Fully local fallback — espeak-ng, no network needed (robotic voice)."""
    if not shutil.which("espeak-ng"):
        raise RuntimeError("espeak-ng not installed")
    wav = out + ".wav"
    subprocess.run(
        ["espeak-ng", "-v", ESPEAK_VOICES[lang], "-s", "150",
         "--stdout", text],
        stdout=open(wav, "wb"), check=True, timeout=600)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", wav,
         "-c:a", "libmp3lame", "-b:a", "128k", out], check=True)
    os.remove(wav)


def make_voiceover(text, lang, out_mp3, prefer=None):
    """Returns provider name used: 'edge-tts', 'gtts' or 'espeak'.

    Chain: edge-tts -> gTTS -> espeak-ng (fully local last resort).
    prefer='espeak' forces the local engine (for offline testing).
    """
    chain = ["edge-tts", "gtts", "espeak"]
    if prefer in chain:
        chain = [prefer] + [p for p in chain if p != prefer]
    last_err = None
    for provider in chain:
        try:
            if provider == "edge-tts":
                tts_edge(text, lang, out_mp3)
            elif provider == "gtts":
                tts_gtts(text, lang, out_mp3)
            else:
                tts_espeak(text, lang, out_mp3)
            if os.path.getsize(out_mp3) > 1000:
                return provider
            raise RuntimeError("empty audio")
        except Exception as e:
            last_err = e
            print(f"[pvideo] {provider} failed ({e}); trying next",
                  file=sys.stderr)
    raise RuntimeError(f"all TTS providers failed (last: {last_err})")


def media_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ---------------------------------------------------------------- cards
def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l / 100.0, s / 100.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def make_card(scene_text, idx, n_scenes, title, font_path, latin_font_path):
    hue = (idx * 47 + 210) % 360
    top, bottom = _hsl(hue, 55, 26), _hsl((hue + 30) % 360, 60, 12)
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c)
    rnd = random.Random(1000 + idx)
    for _ in range(6):
        rr = rnd.randint(120, 320)
        x, y = rnd.randint(-200, W + 200), rnd.randint(-200, H + 200)
        draw.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 255, 255, 16))
    # brand watermark (Latin font — Devanagari fonts may lack Latin glyphs)
    draw.text((70, 90), "PVideo",
              font=ImageFont.truetype(latin_font_path, 44),
              fill=(255, 255, 255, 200))
    # title on first scene
    if title and idx == 0:
        draw.text((W // 2, 300), strip_emoji(title),
                  font=ImageFont.truetype(font_path, 62,
                                          layout_engine=ImageFont.Layout.RAQM),
                  anchor="ma", fill=(255, 214, 90))
    # caption, auto-fit
    size, wrapped, font, th = 96, strip_emoji(scene_text), None, 0
    while size >= 40:
        font = ImageFont.truetype(font_path, size,
                                  layout_engine=ImageFont.Layout.RAQM)
        wrapped = _wrap(draw, scene_text, font, W - 160)
        bb = draw.multiline_textbbox((0, 0), wrapped, font=font, stroke_width=3)
        th = bb[3] - bb[1]
        if th <= 620:
            break
        size -= 8
    draw.multiline_text((W // 2, 960 - th // 2), wrapped, font=font,
                        anchor="ma", align="center", fill="white",
                        stroke_width=3, stroke_fill=(0, 0, 0))
    # progress bar
    bar_w = int(W * (idx + 1) / n_scenes)
    draw.rectangle([0, H - 24, W, H], fill=(0, 0, 0, 160))
    draw.rectangle([0, H - 24, bar_w, H], fill=(255, 214, 90))
    return img


# ---------------------------------------------------------------- ffmpeg
def render_segment(img, dur, out_mp4, zoom="in"):
    tmp = out_mp4 + ".png"
    img.save(tmp)
    frames = max(1, int(dur * FPS))
    z0, z1 = (1.00, 1.10) if zoom == "in" else (1.10, 1.00)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", tmp,
        "-vf", (f"scale=2160:-2,zoompan=z='min(zoom+{((z1 - z0) / frames):.5f},1.5)'"
                 f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS}",),
        "-frames:v", str(frames), "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "veryfast", "-crf", "20", out_mp4], check=True)
    os.remove(tmp)


def concat_mux(seg_paths, audio_mp3, out_path):
    lst = os.path.join(tempfile.gettempdir(), "pvideo_concat.txt")
    with open(lst, "w") as f:
        for s in seg_paths:
            f.write(f"file '{s}'\n")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", lst, "-i", audio_mp3,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-crf", "20", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart", out_path], check=True)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="PVideo v1: script -> vertical MP4")
    ap.add_argument("script", help="path to .txt script (UTF-8)")
    ap.add_argument("-o", "--out", default="output.mp4", help="output MP4 path")
    ap.add_argument("-l", "--lang", default="hi", choices=["hi", "en"])
    ap.add_argument("--title", default="", help="optional title on first card")
    ap.add_argument("--prefer-tts", default=None,
                    choices=["edge-tts", "gtts", "espeak"])
    ap.add_argument("--skip-video", action="store_true",
                    help="only produce voiceover MP3 (debug)")
    a = ap.parse_args()

    for bin in ("ffmpeg", "ffprobe"):
        if not shutil.which(bin):
            sys.exit(f"error: {bin} not found in PATH")

    with open(a.script, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        sys.exit("error: script is empty")

    font = find_font()
    latin_font = find_latin_font()
    print(f"[pvideo] fonts: {font} / {latin_font}")

    scenes = split_scenes(text)
    print(f"[pvideo] {len(scenes)} scenes")

    tmp = tempfile.mkdtemp(prefix="pvideo_")
    audio = os.path.join(tmp, "voice.mp3")
    provider = make_voiceover(text, a.lang, audio, prefer=a.prefer_tts)
    total = media_duration(audio)
    print(f"[pvideo] TTS via {provider}: {total:.1f}s")
    if a.skip_video:
        shutil.copy(audio, a.out + ".mp3")
        print(f"[pvideo] wrote {a.out}.mp3")
        return

    durs = scene_durations(scenes, total)
    segs = []
    for i, (sc, d) in enumerate(zip(scenes, durs)):
        img = make_card(sc, i, len(scenes), a.title, font, latin_font)
        seg = os.path.join(tmp, f"seg{i:03d}.mp4")
        render_segment(img, d, seg, zoom="in" if i % 2 == 0 else "out")
        segs.append(seg)
        print(f"[pvideo] scene {i + 1}/{len(scenes)} ({d:.1f}s)")
    concat_mux(segs, audio, a.out)
    print(f"[pvideo] wrote {a.out}")


if __name__ == "__main__":
    main()

    
