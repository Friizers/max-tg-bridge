#!/usr/bin/env bash
# Повторный вход в MAX, если сессия слетела. Останавливает сервис, заново
# проходит авторизацию по SMS и снова запускает мост.
set -euo pipefail

SERVICE="max-tg-bridge"
cd "$(dirname "$(readlink -f "$0")")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Запусти от root: sudo bash relogin.sh" >&2
  exit 1
fi

# путь к сессии из .env (по умолчанию max_session/session.db)
WORK_DIR="$(grep -E '^MAX_WORK_DIR=' .env 2>/dev/null | cut -d= -f2 || true)"
SESSION="$(grep -E '^MAX_SESSION=' .env 2>/dev/null | cut -d= -f2 || true)"
WORK_DIR="${WORK_DIR:-max_session}"
SESSION="${SESSION:-session.db}"

echo ">> Останавливаю сервис..."
systemctl stop "$SERVICE" 2>/dev/null || true

echo ">> Удаляю старую сессию и захожу заново (придёт SMS — введи код)..."
rm -f "$WORK_DIR/$SESSION"
./venv/bin/python login.py </dev/tty

echo ">> Запускаю сервис..."
systemctl start "$SERVICE"
echo ">> Готово. Мост снова работает."
