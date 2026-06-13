#!/usr/bin/env bash
# Установщик моста MAX <-> Telegram в одну команду.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/YOURGITHUB/max-tg-bridge/main/install.sh)
#
# Перед публикацией замени YOURGITHUB на свой GitHub-логин (в строке REPO_URL ниже
# и в команде выше / в README).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/YOURGITHUB/max-tg-bridge.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-/opt/max-tg-bridge}"
SERVICE="max-tg-bridge"

say() { printf "\n\033[1;32m>> %s\033[0m\n" "$*"; }
err() { printf "\n\033[1;31m!! %s\033[0m\n" "$*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
  err "Запусти от root:  sudo bash <(curl -fsSL .../install.sh)"
  exit 1
fi

say "Устанавливаю системные зависимости (python, git, ffmpeg)..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ffmpeg

say "Загружаю проект в $DIR..."
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || true
else
  rm -rf "$DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

say "Создаю виртуальное окружение и ставлю пакеты..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
  say "Настройка. Введи данные (см. README, как их получить):"
  read -rp "  Telegram Bot Token (@BotFather): " TG_BOT_TOKEN </dev/tty
  read -rp "  ID Telegram-группы (вида -100...): " TG_GROUP_ID </dev/tty
  read -rp "  Телефон аккаунта MAX (+7...): " MAX_PHONE </dev/tty
  umask 077
  cat > .env <<EOF
TG_BOT_TOKEN=$TG_BOT_TOKEN
TG_GROUP_ID=$TG_GROUP_ID
MAX_PHONE=$MAX_PHONE
MAX_WORK_DIR=max_session
MAX_SESSION=session.db
FORWARD_TG_TO_MAX=true
SHOW_SENDER_NAME=true
SYNC_CHATS_ON_START=true
NOTIFY_CALLS=true
DB_PATH=bridge.db
LOG_LEVEL=INFO
EOF
  say ".env создан."
else
  say ".env уже существует — пропускаю настройку."
fi

if [ ! -f "max_session/session.db" ]; then
  say "Авторизация в MAX. Сейчас придёт SMS — введи код:"
  if ! ./venv/bin/python login.py </dev/tty; then
    err "Авторизация MAX не удалась. Проверь MAX_PHONE в $DIR/.env и запусти ещё раз:"
    err "  cd $DIR && ./venv/bin/python login.py"
    exit 1
  fi
else
  say "Сессия MAX уже есть — пропускаю авторизацию."
fi

say "Устанавливаю systemd-сервис..."
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=MAX (userbot) <-> Telegram bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/python $DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE}"

cat <<EOF

================================================================
 Готово! Мост MAX -> Telegram запущен и добавлен в автозапуск.

   Статус:  systemctl status ${SERVICE}
   Логи:    journalctl -u ${SERVICE} -f
   Рестарт: systemctl restart ${SERVICE}
================================================================
EOF
