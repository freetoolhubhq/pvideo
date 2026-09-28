# PVideo — Free Video Generator (P-brand, NEW project)

## Owner brief (2026-09-27 ~20:55 IST, his own idea)
"Free video generator banao. Publish ho sake to publish karenge, nahi to personal use karenge."
- PuchoAI idea REJECTED by owner ("arre nahi yaar") — parked, do not build.
- VPS agent dashboard — paused earlier, stays parked.

## Honest definition of "free"
- NO paid AI-video APIs (Sora/Runway-type cinematic generation is not free/unlimited anywhere).
- Videos render ON the VPS itself: script/text -> TTS voiceover -> 1080x1920 vertical MP4 with visuals + captions. Unlimited, zero per-video cost.
- Personal use first: YouTube Shorts (Valb Army revival!), Reels, X videos. Publish as P-brand product later if good.

## V1 features
1. Script/text input (Hindi + English)
2. Free TTS voiceover (edge-tts, Hindi + English voices, no API key)
3. 9:16 vertical video: animated backgrounds, scene images, bold captions
4. Templates: news Shorts, facts, quotes/motivation
5. Output: MP4 (H.264, WhatsApp/YouTube-compatible encoding — matches owner's device requirement)

## Stack (2GB VPS)
- Python + ffmpeg (raw ffmpeg, not heavy editors — RAM-safe)
- edge-tts for voices; PIL for caption cards; SQLite job queue
- Web UI later (PWA like planned); CLI/API first

## Standing rules
- Email everywhere: ptaleg11@gmail.com
- Branding starts with "P" → **PVideo**

## Phases
1. Engine: text -> video -> captioned vertical MP4 — DONE 2026-09-27 (sample1.mp4, 1080x1920, verified)
2. Templates (news/facts/quotes) + Hindi/English voices
3. Simple web UI: paste script -> download video — DONE 2026-09-27 (Flask app, tested end-to-end, PWA manifest+icons)
4. VPS deploy (needs SSH access — awaited via email)
5. If quality good: publish as P-brand product (PWA) with AdSense/affiliate

## VPS deployment (2026-09-27 night)
- VPS: vps.sivonex.com (185.67.20.116), Ubuntu 24.04.3, 2vCPU/2GB/30GB — Cloudonfire/Virtualizor.
- Panel login from automation is flaky (session bugs); user drives via mobile + Remote Desktop (VNC).
- Deploy path: public GitHub repo `freetoolhubhq/pvideo` → one-command `install.sh`
  (apt deps, pvideo user, venv, systemd, nginx, random Basic Auth creds,
  7-day MP4 cleanup). User pastes ONE curl|bash line into the VNC console as root.
- HTTPS-only since 2026-09-28: installer gets a free Let's Encrypt cert via
  certbot --nginx for <ip-dashes>.nip.io (no DNS setup needed; PVIDEO_DOMAIN
  env overrides with your own domain). Port 80 redirects to HTTPS. Install
  FAILS CLOSED if no certificate can be issued — Basic Auth never goes over
  plain HTTP.
- Fixed 2026-09-27: `render_job` was swallowed by a comment line (auth edit) — worker would NameError every job.
