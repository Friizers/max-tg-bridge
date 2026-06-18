#!/usr/bin/env bash
# Установщик моста MAX <-> Telegram в одну команду.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/Friizers/max-tg-bridge/main/install.sh)
#
# Перед публикацией замени Friizers на свой GitHub-логин (в строке REPO_URL ниже
# и в команде выше / в README).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Friizers/max-tg-bridge.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-/opt/max-tg-bridge}"
SERVICE="max-tg-bridge"

say() { printf "\n\033[1;32m>> %s\033[0m\n" "$*"; }
err() { printf "\033[1;31m!! %s\033[0m\n" "$*" >&2; }

# ask <prompt> <varname> <regex> <hint> — спрашивает, пока не введут непустое
# значение, подходящее под regex. Повторяет запрос при пустом/неверном вводе.
ask() {
  local prompt="$1" __var="$2" regex="$3" hint="$4" val=""
  while true; do
    printf "  %s: " "$prompt" > /dev/tty
    IFS= read -r val < /dev/tty || true
    val="${val#"${val%%[![:space:]]*}"}"   # обрезать пробелы слева
    val="${val%"${val##*[![:space:]]}"}"   # и справа
    if [ -z "$val" ]; then
      err "Пустое значение недопустимо — введи ещё раз."
      continue
    fi
    if [ -n "$regex" ] && ! printf '%s' "$val" | grep -qE "$regex"; then
      err "$hint"
      continue
    fi
    printf -v "$__var" '%s' "$val"
    break
  done
}

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
elif [ -d "$DIR" ]; then
  # Каталог есть, но это не git-репозиторий (напр. залит по SFTP). Пересоздаём
  # как git-репозиторий, но СОХРАНЯЕМ .env, сессию MAX и базу веток.
  say "Каталог не git-репозиторий — пересоздаю, сохраняя .env/сессию/базу..."
  tmp="$(mktemp -d)"
  if [ -f "$DIR/.env" ]; then cp -a "$DIR/.env" "$tmp/.env"; fi
  if [ -d "$DIR/max_session" ]; then cp -a "$DIR/max_session" "$tmp/max_session"; fi
  if [ -f "$DIR/bridge.db" ]; then cp -a "$DIR/bridge.db" "$tmp/bridge.db"; fi
  rm -rf "$DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$DIR"
  if [ -f "$tmp/.env" ]; then cp -a "$tmp/.env" "$DIR/.env"; fi
  if [ -d "$tmp/max_session" ]; then cp -a "$tmp/max_session" "$DIR/max_session"; fi
  if [ -f "$tmp/bridge.db" ]; then cp -a "$tmp/bridge.db" "$DIR/bridge.db"; fi
  rm -rf "$tmp"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

say "Создаю виртуальное окружение и ставлю пакеты..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
  say "Настройка. Введи данные (см. README, как их получить):"
  ask "Telegram Bot Token (@BotFather)" TG_BOT_TOKEN '^[0-9]+:[A-Za-z0-9_-]{30,}$' \
      "Токен вида 123456:AAH... — цифры, двоеточие и длинная часть."
  ask "ID Telegram-группы (-100...)" TG_GROUP_ID '^-100[0-9]{6,}$' \
      "ID супергруппы начинается с -100 и состоит из цифр. Узнать: @getidsbot."
  ask "Телефон аккаунта MAX (+7...)" MAX_PHONE '^\+[0-9]{10,15}$' \
      "Телефон в международном формате, например +79991234567."
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
  ./venv/bin/python login.py </dev/tty || true
  if [ ! -f "max_session/session.db" ]; then
    err "Авторизация MAX не удалась (сессия не создана). Сервис НЕ устанавливаю."
    err "Проверь MAX_PHONE в $DIR/.env и запусти заново:"
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
RestartPreventExitStatus=69

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
