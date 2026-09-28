#!/usr/bin/env python3
"""
PVideo web app — Phase 2.
Mobile-first UI: paste script -> pick language -> "Video Banao" -> download MP4.

Run:  python3 app.py          (serves on port 5050)
Deps: flask, pillow (engine needs edge-tts/gtts + ffmpeg too)

Lean by design for a 2GB VPS: one render job at a time, SQLite queue,
in-memory per-IP rate limit. Set PVIDEO_USER + PVIDEO_PASS env vars to
require login (session cookie via the /login form) before exposing
publicly (no auth if unset).
"""
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory, session, url_for

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE, "jobs")
DB_PATH = os.path.join(BASE, "jobs.db")
ENGINE = os.path.join(BASE, "..", "engine", "make_video.py")

PORT = int(os.environ.get("PVIDEO_PORT", "5050"))

# ---- abuse guards ----
MAX_TEXT = 2000
MIN_TEXT = 10
MAX_TITLE = 80
JOBS_PER_HOUR_PER_IP = 5
_rate = defaultdict(list)  # ip -> [timestamps]
_rate_lock = threading.Lock()

app = Flask(__name__, static_folder="static", template_folder="templates")


# ---------- session auth (PVIDEO_USER + PVIDEO_PASS; login form at /login) ----------
AUTH_USER = os.environ.get("PVIDEO_USER", "")
AUTH_PASS = os.environ.get("PVIDEO_PASS", "")

app.secret_key = os.environ.get("PVIDEO_SECRET", "") or os.urandom(32)


def _is_authed():
    if not (AUTH_USER and AUTH_PASS):
        return True  # not configured -> open (local dev only)
    return session.get("authed") is True


def require_auth(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if _is_authed():
            return f(*a, **kw)
        # API calls get JSON 401; page loads go to the login form
        if request.path.startswith("/api/") or request.path.startswith("/download/"):
            return jsonify({"ok": False, "error": "auth required"}), 401
        return redirect(url_for("login", next=request.path))
    return wrapper


LOGIN_PAGE = """<!doctype html><html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PVideo Login</title>
<style>body{{font-family:system-ui;background:#111;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
.card{{background:#1c1c1c;padding:28px;border-radius:14px;width:88%;max-width:340px;box-shadow:0 4px 24px #000}}
h1{{margin:0 0 4px;font-size:22px}}.sub{{color:#999;font-size:13px;margin-bottom:18px}}
input{{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border-radius:8px;border:1px solid #444;background:#222;color:#fff;font-size:16px}}
button{{width:100%;padding:12px;margin-top:10px;border:0;border-radius:8px;background:#e91e63;color:#fff;font-size:17px;font-weight:700}}
.err{{color:#ff8080;font-size:14px;margin:6px 0;min-height:20px}}</style></head>
<body><div class="card"><h1>PVideo</h1><div class="sub">Login karo</div>
<div class="err">{err}</div>
<form method="post"><input name="username" placeholder="Username" autocomplete="username" required>
<input type="password" name="password" placeholder="Password" autocomplete="current-password" required>
<input type="hidden" name="next" value="{nxt}">
<button type="submit">Login</button></form></div></body></html>"""


@app.get("/login")
def login():
    if _is_authed():
        return redirect(request.args.get("next") or "/")
    return LOGIN_PAGE.format(err="", nxt=request.args.get("next", "/"))


@app.post("/login")
def login_post():
    nxt = request.form.get("next") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    user = request.form.get("username", "")
    pw = request.form.get("password", "")
    if AUTH_USER and user == AUTH_USER and pw == AUTH_PASS:
        session["authed"] = True
        session.permanent = True
        return redirect(nxt)
    return LOGIN_PAGE.format(err="Galat username ya password.", nxt=nxt), 401


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------- db ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    os.makedirs(JOBS_DIR, exist_ok=True)
    con = db()
    con.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,          -- queued|working|done|error
            lang TEXT NOT NULL,
            title TEXT,
            ip TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT
        )"""
    )
    con.commit()
    con.close()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- rate limit ----------
def allowed(ip):
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate[ip] if now - t < 3600]
        _rate[ip] = hits
        if len(hits) >= JOBS_PER_HOUR_PER_IP:
            return False
        hits.append(now)
        return True


def client_ip():
    # X-Forwarded-For only trusted if you run behind your own proxy; else direct.
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


# ---------- background worker (one job at a time) ----------


def render_job(job_id, text, lang, title):
    out = os.path.join(JOBS_DIR, job_id + ".mp4")
    cmd = [sys.executable, ENGINE, "--text", text, "--lang", lang, "--out", out]
    if title:
        cmd += ["--title", title]
    # cwd=BASE so engine-relative temp paths (if any) stay inside app/
    proc = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, timeout=1800)
    return proc


def worker():
    while True:
        try:
            con = db()
            row = con.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row:
                job_id = row["id"]
                con.execute("UPDATE jobs SET status='working' WHERE id=?", (job_id,))
                con.commit()
                meta = con.execute(
                    "SELECT lang, title FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                # NOTE: text is not stored in DB (keeps DB small); re-read from job file.
                with open(os.path.join(JOBS_DIR, job_id + ".txt"), encoding="utf-8") as f:
                    text = f.read()
                con.close()
                try:
                    proc = render_job(job_id, text, meta["lang"], meta["title"] or "")
                    con = db()
                    if proc.returncode == 0 and os.path.exists(os.path.join(JOBS_DIR, job_id + ".mp4")):
                        con.execute(
                            "UPDATE jobs SET status='done', finished_at=? WHERE id=?",
                            (utcnow(), job_id),
                        )
                    else:
                        err = (proc.stderr or "")[-500:] or "render failed"
                        con.execute(
                            "UPDATE jobs SET status='error', error=?, finished_at=? WHERE id=?",
                            (err, utcnow(), job_id),
                        )
                    con.commit()
                    con.close()
                except Exception as e:  # noqa: BLE001
                    con = db()
                    con.execute(
                        "UPDATE jobs SET status='error', error=?, finished_at=? WHERE id=?",
                        (str(e)[-500:], utcnow(), job_id),
                    )
                    con.commit()
                    con.close()
                # free the raw script text file after render
                try:
                    os.remove(os.path.join(JOBS_DIR, job_id + ".txt"))
                except OSError:
                    pass
            else:
                con.close()
                time.sleep(2)
        except Exception:  # noqa: BLE001 - worker must never die
            time.sleep(5)


# ---------- routes ----------
@app.get("/")
@require_auth
def index():
    return send_from_directory(os.path.join(BASE, "templates"), "index.html")


@app.post("/api/jobs")
@require_auth
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    lang = (data.get("lang") or "hi").strip().lower()
    title = (data.get("title") or "").strip()

    if lang not in ("hi", "en"):
        return jsonify({"ok": False, "error": "lang must be hi or en"}), 400
    if not (MIN_TEXT <= len(text) <= MAX_TEXT):
        return jsonify(
            {"ok": False, "error": f"text must be {MIN_TEXT}-{MAX_TEXT} characters"}
        ), 400
    if len(title) > MAX_TITLE:
        return jsonify({"ok": False, "error": f"title max {MAX_TITLE} characters"}), 400
    # strip control chars that break ffmpeg drawtext
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    ip = client_ip()
    if not allowed(ip):
        return jsonify({"ok": False, "error": "hourly limit reached, try later"}), 429

    job_id = uuid.uuid4().hex[:12]
    with open(os.path.join(JOBS_DIR, job_id + ".txt"), "w", encoding="utf-8") as f:
        f.write(text)
    con = db()
    con.execute(
        "INSERT INTO jobs (id, status, lang, title, ip, created_at) VALUES (?,?,?,?,?,?)",
        (job_id, "queued", lang, title, ip, utcnow()),
    )
    con.commit()
    con.close()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/jobs/<job_id>")
@require_auth
def job_status(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
        return jsonify({"ok": False, "error": "bad id"}), 400
    con = db()
    row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    con.close()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    out = {"ok": True, "job_id": job_id, "status": row["status"], "lang": row["lang"]}
    if row["status"] == "done":
        out["download_url"] = f"/download/{job_id}"
    if row["status"] == "error":
        out["error"] = row["error"] or "render failed"
    return jsonify(out)


@app.get("/download/<job_id>")
@require_auth
def download(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
        return jsonify({"ok": False, "error": "bad id"}), 400
    path = os.path.join(JOBS_DIR, job_id + ".mp4")
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "not ready"}), 404
    return send_file(path, mimetype="video/mp4", as_attachment=True,
                     download_name=f"pvideo-{job_id}.mp4")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "pvideo"})


_worker_started = False


def ensure_worker():
    """Start the single background render thread (idempotent).

    Called at import time so it also runs under gunicorn, where the
    __main__ block never executes. Safe with gunicorn -w 1.
    """
    global _worker_started
    if not _worker_started:
        init_db()
        threading.Thread(target=worker, daemon=True, name="pvideo-worker").start()
        _worker_started = True


ensure_worker()


if __name__ == "__main__":
    print(f"PVideo app on http://127.0.0.1:{PORT}  (engine: {ENGINE})", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
