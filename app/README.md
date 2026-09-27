# PVideo Web App (Phase 2)

Mobile-first web UI over the v1 engine (`../engine/make_video.py`).
Paste a script → pick Hindi/English → **Video Banao** → download the MP4.

## Run

```bash
cd ~/workspace/pvideo/app
pip install flask pillow        # one time (engine needs edge-tts/gtts + ffmpeg too)
python3 app.py                  # serves http://127.0.0.1:5050
# custom port:  PVIDEO_PORT=8080 python3 app.py
```

Open the URL on your phone (same network) — the page is mobile-first and
installable (PWA: manifest + service worker + icons).

## API

- `POST /api/jobs` — `{"text": "...", "lang": "hi"|"en", "title": "..."}` → `{"ok": true, "job_id": "..."}`
  - Validation: text 10–2000 chars, title ≤ 80 chars.
  - Rate limit: 5 jobs/hour per IP (in-memory).
- `GET /api/jobs/<id>` — `{"ok": true, "status": "queued|working|done|error", "download_url": "/download/<id>"}` (+ `error` when failed)
- `GET /download/<id>` — the finished MP4 (attachment)
- `GET /health` — liveness check

## How it works

- Jobs go into SQLite `jobs.db` (`queued` → `working` → `done`/`error`).
- One background worker thread renders jobs **one at a time** via subprocess
  (`python3 ../engine/make_video.py …`) — safe for a 2GB VPS.
- Raw script text is stored as `jobs/<id>.txt` only until render finishes, then deleted.

## Limits (honest)

- Render takes ~1–3 min per ~30 s video on a small CPU; one at a time.
- Free TTS (gTTS/edge-tts) can throttle under heavy bulk use.
- **No login yet — add a password before any public exposure** (see "What's next").

## What's next

1. Password gate (HTTP basic auth or simple token) before VPS/public deploy.
2. Templates (news / facts / quotes) as one-tap presets.
3. VPS deploy: systemd service + nginx + HTTPS (needs SSH access).
4. Optional: AdSense/affiliate slots if published as a product.
