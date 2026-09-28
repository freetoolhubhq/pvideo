#!/usr/bin/env bash
#
# PVideo one-command installer — Ubuntu 24.04 (run as root).
#
# Secure by design: PVideo is served ONLY over HTTPS (free Let's Encrypt
# certificate). Port 80 exists only for the certificate challenge and
# redirects everything to HTTPS. Basic-Auth login is never sent in the clear.
#
# Usage (paste into the VPS console as root):
#   curl -sSL https://raw.githubusercontent.com/freetoolhubhq/pvideo/main/deploy/install.sh | bash
#
# Optional: use your own domain (must already point to this VPS):
#   PVIDEO_DOMAIN=vps.example.com curl -sSL https://raw.githubusercontent.com/freetoolhubhq/pvideo/main/deploy/install.sh | bash
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
REPO="https://github.com/freetoolhubhq/pvideo.git"
APP_DIR="/opt/pvideo"

echo "[pvideo] 1/8 system packages..."
apt-get update -y -qq || true
apt-get install -y -qq python3 python3-venv python3-pip ffmpeg espeak-ng \
  nginx git curl certbot python3-certbot-nginx fonts-dejavu-core > /dev/null

echo "[pvideo] 2/8 service user..."
id pvideo >/dev/null 2>&1 || useradd -r -m -s /bin/false pvideo

echo "[pvideo] 3/8 app code..."
ENV_BAK=""
[ -f "$APP_DIR/.env" ] && ENV_BAK="$(cat $APP_DIR/.env)"
rm -rf "$APP_DIR"
git clone --depth 1 -q "$REPO" "$APP_DIR"

echo "[pvideo] 4/8 python environment..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/deploy/requirements.txt"

mkdir -p "$APP_DIR/app/jobs"
chown -R pvideo:pvideo "$APP_DIR"

echo "[pvideo] 5/8 login credentials..."
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

echo "[pvideo] 6/8 systemd service..."
cp "$APP_DIR/deploy/pvideo.service" /etc/systemd/system/pvideo.service
systemctl daemon-reload
systemctl enable -q --now pvideo

echo "[pvideo] 7/8 HTTPS (nginx + free Let's Encrypt certificate)..."
PUBLIC_IP="$(curl -s --max-time 10 ifconfig.me 2>/dev/null || true)"
[ -z "$PUBLIC_IP" ] && PUBLIC_IP="$(hostname -I | awk '{print $1}')"
# nip.io gives this VPS a public hostname for free — no DNS setup needed.
NIP_DOMAIN="$(printf '%s' "$PUBLIC_IP" | tr '.' '-').nip.io"
DOMAIN="${PVIDEO_DOMAIN:-$NIP_DOMAIN}"
echo "[pvideo] certificate domain: $DOMAIN"

sed "s/PVIDEO_DOMAIN_PLACEHOLDER/$DOMAIN/" \
  "$APP_DIR/deploy/nginx-pvideo.conf" > /etc/nginx/sites-available/pvideo
ln -sf /etc/nginx/sites-available/pvideo /etc/nginx/sites-enabled/pvideo
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

if ! certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
     --register-unsafely-without-email --redirect --keep-until-expiry -q; then
  cat >&2 <<EOF

[pvideo] ERROR: could not get an HTTPS certificate for $DOMAIN.
Port 80 of this VPS must be reachable from the internet.
Check the provider firewall, then re-run this installer.

PVideo was NOT started over plain HTTP — your login stays protected.
EOF
  exit 1
fi

# sanity: plain HTTP must redirect to HTTPS, never serve the app
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
  "http://$DOMAIN/health" || true)"
if [ "$HTTP_CODE" != "301" ] && [ "$HTTP_CODE" != "308" ]; then
  echo "[pvideo] WARNING: HTTP->HTTPS redirect check returned $HTTP_CODE" >&2
fi

echo "[pvideo] 8/8 cleanup policy (videos older than 7 days)..."
printf '0 4 * * * pvideo find %s/app/jobs -name "*.mp4" -mtime +7 -delete\n' \
  "$APP_DIR" > /etc/cron.d/pvideo-cleanup
chmod 644 /etc/cron.d/pvideo-cleanup

CREDS_USER="$(grep '^PVIDEO_USER=' $APP_DIR/.env | cut -d= -f2)"
CREDS_PASS="$(grep '^PVIDEO_PASS=' $APP_DIR/.env | cut -d= -f2)"

sleep 5
if systemctl is-active -q pvideo && curl -sk -o /dev/null -w "%{http_code}" \
    --max-time 15 "https://$DOMAIN/health" | grep -q 200; then
  STATUS="RUNNING ✓ (HTTPS)"
else
  STATUS="CHECK MANUALLY (systemctl status pvideo; journalctl -u pvideo -n 50)"
fi

cat <<EOF

====================================================
 PVideo install complete — $STATUS

 Open on your phone (secure):
   https://$DOMAIN

 Login username : $CREDS_USER
 Login password : $CREDS_PASS
 (also saved in /root/pvideo-credentials.txt)

 Paste Hindi/English script -> Video Banao -> download.
 Certificate auto-renews (certbot timer).
====================================================
EOF
