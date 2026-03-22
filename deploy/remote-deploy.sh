#!/usr/bin/env bash
set -euo pipefail

APP_NAME="autodosie_bot"
APP_USER="autobot"
APP_ROOT="/home/${APP_USER}"
WORK_TREE="${APP_ROOT}/apps/${APP_NAME}"
VENV_DIR="${APP_ROOT}/.venvs/${APP_NAME}"
ENV_FILE="${APP_ROOT}/apps/shared/${APP_NAME}.env"
SERVICE_NAME="autodosie-bot.service"

if [[ ! -d "${WORK_TREE}" ]]; then
    echo "Missing work tree: ${WORK_TREE}"
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Missing environment file: ${ENV_FILE}"
    exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install --no-build-isolation --editable "${WORK_TREE}"

sudo /usr/bin/systemctl daemon-reload
sudo /usr/bin/systemctl restart "${SERVICE_NAME}"
sudo /usr/bin/systemctl --no-pager --full status "${SERVICE_NAME}"

