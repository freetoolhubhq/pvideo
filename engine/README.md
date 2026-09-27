# PVideo v1 — Free Video Generator Engine

Turns a text script into a vertical **9:16 MP4** (1080×1920, 30fps) with
voiceover + big caption cards. **100% free**: no paid APIs, no API keys —
videos render locally with ffmpeg + free TTS.

## Quick start

```bash
# dependencies (one time)
pip install edge-tts gtts pillow

# Hindi Shorts
python3 engine/make_video.py \
  --text "आपकी स्क्रिप्ट यहाँ। दूसरा वाक्य।" \
  --lang hi \
  --title "मज़ेदार तथ्य 🔥" \
  --out samples/myvideo.mp4

# English video
python3 engine/make_video.py \
  --text "First sentence. Second sentence." \
  --lang en \
  --out samples/myvideo.mp4
```

Options: `--title` (shown on first scene), `--keep-temp` (debug).

## How it works

1. **Scenes** — script split on sentence enders (`। . ! ?`), merged to ≤90 chars.
2. **Voiceover** — one MP3 for the whole script:
   - Tries **edge-tts** first (hi-IN-SwaraNeural / en-IN-NeerjaNeural, free, no key).
   - On any failure → **gTTS** fallback (free, no key, Indian accent via `co.in`).
3. **Timing** — total MP3 duration via ffprobe, split across scenes
   proportional to character count (min 1.8 s/scene so captions stay readable).
4. **Cards** — PIL renders one 1080×1920 PNG per scene: gradient background
   (hue varies per scene), bold Devanagari-safe captions (RAQM/harfbuzz
   shaping), PVideo watermark, progress bar.
5. **Assemble** — ffmpeg: slow zoom per scene (`zoompan`) → concat →
   mux AAC audio. Output: H.264 + AAC, `yuv420p`, `+faststart`
   (plays on WhatsApp / YouTube Shorts / Reels).

## Voices used

| Lang | Primary (edge-tts)      | Fallback (gTTS) |
|------|-------------------------|-----------------|
| hi   | hi-IN-SwaraNeural (F)   | lang=hi (Google) |
| en   | en-IN-NeerjaNeural (F)  | lang=en, Indian accent |

## Limitations (honest)

- **Timing is approximate.** Scene cuts are distributed by character count,
  assuming uniform speaking rate. A caption can appear ~0.5–1 s before/after
  its spoken line. (Per-scene TTS would be exact but sounds choppy.)
- **Render speed.** On a small CPU, ~35 s of video takes ~2–4 min
  (zoompan encode per scene). Overnight batches are fine; not real-time.
- **TTS quality.** Free voices are good but not studio-grade. edge-tts needs
  direct internet to Microsoft; behind strict proxies it falls back to gTTS
  (slightly more robotic, still clear Hindi/English).
- **Visuals are graphic cards**, not AI video. Cinematic AI clips
  (Sora/Runway-style) are never free/unlimited — this engine is honest about
  that and optimizes for Shorts-style fact/news/quote videos.
- **gTTS rate limits.** Google's unofficial endpoint can throttle heavy use;
  for bulk rendering, add pauses between runs.
- Fonts: uses system Noto Sans Devanagari Bold if present, else
  `engine/fonts/*.ttf` if you drop files there.
- **No emoji in visuals.** Emoji are stripped from cards/titles (no color-emoji
  font on the server); the voiceover still reads the words.

## Files

- `engine/make_video.py` — the engine (CLI)
- `engine/fonts/` — optional bundled TTFs (empty by default; system fonts used)
- `samples/sample1.mp4` — demo Hindi facts Shorts
