# PVideo — Free Video Generator

Type/paste a script (Hindi or English) → get a vertical **1080×1920 MP4**
with AI voiceover and animated captions. Renders on your own server —
no coins, no credits, no paid video APIs.

**V1:** script → free TTS voiceover (edge-tts → gTTS → local espeak-ng
fallback) → captioned 9:16 MP4 (H.264/AAC, WhatsApp + YouTube Shorts ready).

## Deploy on Ubuntu 24.04 VPS (one command, as root)

```bash
curl -sSL https://raw.githubusercontent.com/freetoolhubhq/pvideo/main/deploy/install.sh | bash
```

Installs Python env, ffmpeg, espeak-ng, nginx + systemd service, and prints
your login + URL. Then open `http://YOUR_SERVER_IP` on your phone.

## Local dev

```bash
python3 -m venv venv && venv/bin/pip install -r deploy/requirements.txt
venv/bin/python engine/make_video.py --text "नमस्ते दुनिया।" --lang hi --out out.mp4
PVIDEO_USER=admin PVIDEO_PASS=secret venv/bin/python app/app.py  # :5050
```

## Layout

- `engine/` — render pipeline (TTS → caption cards → ffmpeg)
- `app/` — mobile-first Flask UI + SQLite job queue (one render at a time)
- `deploy/` — `install.sh`, systemd unit, nginx config, requirements
