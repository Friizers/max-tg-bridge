#!/usr/bin/env bash
# Удаление моста MAX <-> Telegram.
set -euo pipefail

DIR="${DIR:-/opt/max-tg-bridge}"
SERVICE="max-tg-bridge"

if [ "$(id -u)" -ne 0 ]; then
  echo "Запусти от root: sudo bash uninstall.sh" >&2
  exit 1
fi

systemctl disable --now "${SERVICE}" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload

echo "Сервис удалён."
echo "Файлы проекта остались в $DIR (там же .env и сессия MAX)."
echo "Чтобы удалить полностью:  rm -rf $DIR"
