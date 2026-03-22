#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root."
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="autodosie_bot"
APP_USER="autobot"
APP_GROUP="autobot"
APP_ROOT="/home/${APP_USER}"
BASE_DIR="${APP_ROOT}/apps"
WORK_TREE="${BASE_DIR}/${APP_NAME}"
SHARED_DIR="${BASE_DIR}/shared"
VENV_BASE="${APP_ROOT}/.venvs"
ENV_FILE="${SHARED_DIR}/${APP_NAME}.env"
SSH_DIR="${APP_ROOT}/.ssh"
AUTHORIZED_KEYS_FILE="${SSH_DIR}/authorized_keys"
NGINX_SITE_NAME="autodosie.ru.conf"
NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"

if ! id "${APP_USER}" >/dev/null 2>&1; then
    echo "User ${APP_USER} does not exist."
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1 || ! command -v nginx >/dev/null 2>&1; then
    apt-get update
    apt-get install -y rsync nginx
fi

install -d -o "${APP_USER}" -g "${APP_GROUP}" "${BASE_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" "${WORK_TREE}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" "${SHARED_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" "${VENV_BASE}"
install -d -m 0700 -o "${APP_USER}" -g "${APP_GROUP}" "${SSH_DIR}"

if [[ ! -f "${AUTHORIZED_KEYS_FILE}" ]]; then
    touch "${AUTHORIZED_KEYS_FILE}"
    chown "${APP_USER}:${APP_GROUP}" "${AUTHORIZED_KEYS_FILE}"
    chmod 0600 "${AUTHORIZED_KEYS_FILE}"
fi

install -m 0644 "${SCRIPT_DIR}/autodosie-bot.service" /etc/systemd/system/autodosie-bot.service
install -m 0644 "${SCRIPT_DIR}/autodosie-web.service" /etc/systemd/system/autodosie-web.service
install -m 0440 "${SCRIPT_DIR}/autodosie-bot.sudoers" /etc/sudoers.d/autodosie-bot
install -m 0644 "${SCRIPT_DIR}/autodosie.ru.nginx.conf" "${NGINX_SITE_AVAILABLE}"
ln -sfn "${NGINX_SITE_AVAILABLE}" "${NGINX_SITE_ENABLED}"

if [[ ! -f "${ENV_FILE}" ]]; then
    cat > "${ENV_FILE}" <<'EOF'
BOT_TOKEN=
LOG_LEVEL=INFO
VEHICLE_DATA_PROVIDER=free
REQUEST_TIMEOUT_SECONDS=20
GIBDD_CAPTCHA_WAIT_SECONDS=45
GIBDD_CAPTCHA_POLL_INTERVAL_SECONDS=5
SITE_NAME=AutoDosie
SITE_URL=https://autodosie.ru
WEB_HOST=127.0.0.1
WEB_PORT=8000
EOF
    chown root:"${APP_GROUP}" "${ENV_FILE}"
    chmod 0640 "${ENV_FILE}"
fi

systemctl daemon-reload
systemctl enable autodosie-bot.service
systemctl enable autodosie-web.service
nginx -t
systemctl enable nginx

echo "Bootstrap complete."
echo "Next steps:"
echo "1. Add a deploy public key to ${AUTHORIZED_KEYS_FILE}"
echo "2. Edit ${ENV_FILE}"
echo "3. Point autodosie.ru and www.autodosie.ru to this server"
echo "4. Add GitHub secrets DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY"
echo "5. Push to main and GitHub Actions will deploy automatically"
