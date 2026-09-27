#!/usr/bin/env bash
#
# PVideo one-command installer — Ubuntu 24.04 (run as root).
# Usage (paste into the VPS console as root):
#   curl -sSL https://raw.githubusercontent.com/freetoolhubhq/pvideo/main/deploy/install.sh | bash
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
REPO="https://github.com/freetoolhubhq/pvideo.git"
APP_DIR="/opt/pvideo"

echo "[pvideo] 1/7 system packages..."
apt-get update -y -qq || true
apt-get install -y -qq python3 python3-venv python3-pip ffmpeg espeak-ng \
  nginx git curl fonts-dejavu-core > /dev/null

echo "[pvideo] 2/7 service user..."
id pvideo >/dev/null 2>&1 || useradd -r -m -s /bin/false pvideo

echo "[pvideo] 3/7 app code..."
ENV_BAK=""
[ -f "$APP_DIR/.env" ] && ENV_BAK="$(cat $APP_DIR/.env)"
rm -rf "$APP_DIR"
git clone --depth 1 -q "$REPO" "$APP_DIR"

echo "[pvideo] 4/7 python environment..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/deploy/requirements.txt"

mkdir -p "$APP_DIR/app/jobs"
chown -R pvideo:pvideo "$APP_DIR"

echo "[pvideo] 5/7 login credentials..."
if [ -n "$ENV_BAK" ]; then
  printf '%s\n' "$ENV_BAK" > "$APP_DIR/.env"
  echo "[pvideo] kept existing credentials"
else
  PVIDEO_USER="naiem"
  PVIDEO_PASS="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)" || true
  printf 'PVIDEO_PORT=5050\nPVIDEO_USER=%s\nPVIDEO_PASS=%s\n' \
    "$PVIDEO_USER" "$PVIDEO_PASS" > "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
chown pvideo:pvideo "$APP_DIR/.env"
cp "$APP_DIR/.env" /root/pvideo-credentials.txt
chmod 600 /root/pvideo-credentials.txt

echo "[pvideo] 6/7 systemd + nginx..."
cp "$APP_DIR/deploy/pvideo.service" /etc/systemd/system/pvideo.service
systemctl daemon-reload
systemctl enable -q --now pvideo
cp "$APP_DIR/deploy/nginx-pvideo.conf" /etc/nginx/sites-available/pvideo
ln -sf /etc/nginx/sites-available/pvideo /etc/nginx/sites-enabled/pvideo
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

echo "[pvideo] 7/7 cleanup policy (videos older than 7 days)..."
printf '0 4 * * * pvideo find %s/app/jobs -name "*.mp4" -mtime +7 -delete\n' \
  "$APP_DIR" > /etc/cron.d/pvideo-cleanup
chmod 644 /etc/cron.d/pvideo-cleanup

PUBLIC_IP="$(curl -s --max-time 10 ifconfig.me 2>/dev/null || true)"
[ -z "$PUBLIC_IP" ] && PUBLIC_IP="$(hostname -I | awk '{print $1}')"
CREDS_USER="$(grep '^PVIDEO_USER=' $APP_DIR/.env | cut -d= -f2)"
CREDS_PASS="$(grep '^PVIDEO_PASS=' $APP_DIR/.env | cut -d= -f2)"

sleep 5
if systemctl is-active -q pvideo && curl -s -o /dev/null -w "%{http_code}" \
    http://127.0.0.1:5050/health | grep -q 200; then
  STATUS="RUNNING ✓"
else
  STATUS="CHECK MANUALLY (systemctl status pvideo)"
fi

cat <<EOF

====================================================
 PVideo install complete — $STATUS

 Open on your phone:
   http://$PUBLIC_IP

 Login username : $CREDS_USER
 Login password : $CREDS_PASS
 (also saved in /root/pvideo-credentials.txt)

 Paste Hindi/English script -> Video Banao -> download.
====================================================
EOF
