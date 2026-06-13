# Мост MAX ⇄ Telegram (userbot)

Зеркало между мессенджером **MAX** (РФ) и **Telegram**.

- **MAX-сторона — это ВАШ личный аккаунт (userbot).** Бот авторизуется по вашему
  номеру телефона MAX и работает от вашего имени: читает все ваши чаты и отправляет
  сообщения как вы. Отдельный «бот-аккаунт» в MAX не нужен.
- **Telegram-сторона — обычный бот** в вашей супергруппе-форуме.

Логика:

- **MAX → Telegram.** Для каждого чата MAX бот **сам создаёт отдельную тему (ветку)**
  в Telegram-группе и пересылает туда текст, фото, видео, аудио, файлы, стикеры.
- **Telegram → MAX.** Всё, что вы пишете в соответствующей теме Telegram, уходит
  обратно в тот же чат MAX (текст и вложения) — от вашего имени.

Связь «чат MAX ↔ тема Telegram» хранится в SQLite и переживает перезапуск.

```
   MAX чат A  ─┐                        ┌─ Telegram тема «Чат A»
   MAX чат B  ─┼──  [ бот-мост ]  ──────┼─ Telegram тема «Чат B»
   MAX чат C  ─┘   (ваш аккаунт MAX)    └─ Telegram тема «Чат C»
```

---

## ⚠️ Прочитайте до начала

- **Это неофициальный (внутренний) протокол MAX.** Используется библиотека
  [`maxapi-python`](https://pypi.org/project/maxapi-python/) (userbot). Это против
  правил сервиса MAX, и **теоретически возможна блокировка аккаунта**. Вы действуете
  на свой риск, со своим аккаунтом.
- **Первый вход — интерактивный:** при первой авторизации нужно один раз ввести
  **код из SMS** (и пароль, если включена 2FA). На сервере это делается через
  `login.py` внутри `tmux`/`screen`. Дальше сессия сохраняется и всё работает само.
- Зеркалятся **все** ваши чаты MAX (по мере поступления сообщений). Собственные
  сообщения (и отправленные из MAX, и пересланные мостом из Telegram) в Telegram
  **не** дублируются — чтобы не было эхо-петли.
- Скачивание файлов из Telegram ограничено **20 МБ** (лимит Telegram Bot API).

---

## 🚀 Быстрая установка (одна команда)

Сначала подготовь данные (раздел «Шаг 1» и «Шаг 2» ниже): **токен бота**,
**ID группы**, **телефон MAX**. Затем на сервере Ubuntu выполни от root:

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/YOURGITHUB/max-tg-bridge/main/install.sh)
```

Скрипт сам поставит зависимости (включая `ffmpeg`), скачает проект в
`/opt/max-tg-bridge`, спросит токен/ID/телефон, проведёт авторизацию в MAX
(введёшь код из SMS) и запустит сервис с автозапуском.

> Замени `YOURGITHUB` на свой GitHub-логин (туда же, куда залит этот репозиторий).
> Удаление: `sudo bash /opt/max-tg-bridge/uninstall.sh`.

Ниже — то же самое вручную, по шагам.

---

## Шаг 1. Бот в Telegram

1. **[@BotFather](https://t.me/BotFather)** → `/newbot` → имя и username.
   Скопируйте **токен** → это `TG_BOT_TOKEN`.
2. Отключите приватность (чтобы бот видел сообщения в группе):
   `/setprivacy` → выберите бота → **Disable**.
3. Создайте **супергруппу** и включите в ней **Темы (Topics)**:
   *Управление группой → Темы*.
4. Добавьте бота в группу и сделайте **администратором** с правом
   **«Управление темами»** (Manage Topics).
5. Узнайте ID группы: отправьте в любой теме команду **`/id`** — бот ответит
   `chat_id` (вида `-100…`). Это `TG_GROUP_ID`.

## Шаг 2. Данные аккаунта MAX

Нужен только **номер телефона** вашего аккаунта MAX (`MAX_PHONE`). Код из SMS
введёте на шаге авторизации.

---

## Шаг 3. Установка на Ubuntu

Нужен **Python 3.10+** (Ubuntu 22.04/24.04 — из коробки).

```bash
# 1. Системные зависимости
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git tmux ffmpeg
# ffmpeg нужен для видеостикеров (.webm) — извлечение кадра с прозрачностью

# 2. Положите проект в /opt/max-tg-bridge
sudo mkdir -p /opt/max-tg-bridge
sudo chown $USER:$USER /opt/max-tg-bridge
# ... скопируйте файлы проекта сюда ...
cd /opt/max-tg-bridge

# 3. Виртуальное окружение и пакеты
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Конфигурация
cp .env.example .env
nano .env        # TG_BOT_TOKEN, TG_GROUP_ID, MAX_PHONE
```

## Шаг 4. Первичная авторизация MAX (один раз, вручную)

```bash
cd /opt/max-tg-bridge
./venv/bin/python login.py
```

Введите код из SMS (и пароль 2FA, если есть). При успехе появится
`✅ Авторизация успешна` и создастся файл сессии в `max_session/`.
Дальше код вводить не нужно.

> На сервере без графики запускайте в `tmux` (`tmux new -s max`), чтобы не потерять
> сессию при разрыве SSH. Выйти из tmux: `Ctrl+b`, затем `d`.

### Проверка моста вручную

```bash
./venv/bin/python bot.py
```

Напишите себе в любой чат MAX — в Telegram создастся тема с этим сообщением.
Ответьте в этой теме — сообщение придёт в MAX. Работает — останавливаем
(`Ctrl+C`) и ставим как сервис.

## Шаг 5. Автозапуск через systemd

```bash
# Отдельный пользователь
sudo useradd -r -m -s /usr/sbin/nologin maxbridge
sudo cp -r /opt/max-tg-bridge /opt/_tmp && sudo rm -rf /opt/max-tg-bridge
sudo mv /opt/_tmp /opt/max-tg-bridge
sudo chown -R maxbridge:maxbridge /opt/max-tg-bridge

# Если авторизацию делали под своим пользователем — повторите login.py под maxbridge,
# либо просто перенесите каталог max_session/ и выставьте на него права maxbridge.
sudo -u maxbridge /opt/max-tg-bridge/venv/bin/python /opt/max-tg-bridge/login.py

# Установка юнита
sudo cp systemd/max-tg-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now max-tg-bridge

# Статус и логи
systemctl status max-tg-bridge
journalctl -u max-tg-bridge -f
```

После правок `.env` — `sudo systemctl restart max-tg-bridge`.

---

## Файл .env — параметры

| Переменная          | По умолчанию    | Описание |
|---------------------|-----------------|----------|
| `TG_BOT_TOKEN`      | —               | Токен Telegram-бота от @BotFather |
| `TG_GROUP_ID`       | —               | ID супергруппы-форума (`-100…`) |
| `MAX_PHONE`         | —               | Телефон вашего аккаунта MAX (`+7…`) |
| `MAX_WORK_DIR`      | `max_session`   | Каталог файла сессии MAX |
| `MAX_SESSION`       | `session.db`    | Имя файла сессии MAX |
| `FORWARD_TG_TO_MAX` | `true`          | Пересылать ли из Telegram обратно в MAX |
| `SHOW_SENDER_NAME`  | `true`          | Подписывать сообщения именем отправителя |
| `DB_PATH`           | `bridge.db`     | Файл базы со связями тем |
| `LOG_LEVEL`         | `INFO`          | Уровень логов |

---

## Траблшутинг

- **При запуске `bot.py` просит код из SMS / зависает** — не выполнена авторизация.
  Запустите `python login.py` интерактивно (в tmux), затем стартуйте бота/сервис.
- **`bot.py` под systemd падает с ошибкой ввода** — сервис не интерактивный.
  Сессия должна существовать заранее (см. шаг 4); файл `max_session/session.db`
  должен принадлежать пользователю `maxbridge`.
- **Темы не создаются** — бот не админ группы / нет права «Управление темами», либо
  в группе не включены Темы (Topics).
- **Бот не видит сообщения в Telegram** — не отключён Privacy Mode (`/setprivacy`).
- **Сообщения из Telegram не уходят в MAX** — пишите **в теме**, созданной мостом
  (она связана с MAX-чатом). «General» и ручные несвязанные темы игнорируются.
  Проверьте `FORWARD_TG_TO_MAX=true`.
- **Аккаунт MAX «разлогинило»** — удалите `max_session/` и пройдите `login.py`
  заново. Если повторяется часто — возможен анти-фрод MAX (см. предупреждение выше).
- **Большой файл не ушёл из Telegram** — ограничение Telegram Bot API 20 МБ.

## Состав проекта

```
bot.py          точка входа: userbot MAX + бот Telegram одновременно
login.py        одноразовая интерактивная авторизация MAX (SMS-код)
config.py       чтение настроек из .env
storage.py      SQLite: связи MAX-чат ↔ Telegram-тема
max_to_tg.py    MAX → Telegram (on_message, авто-темы, пересылка медиа)
tg_to_max.py    Telegram → MAX (хендлеры aiogram, команда /id)
requirements.txt, .env.example, systemd/max-tg-bridge.service
```

## Технологии

- [`maxapi-python`](https://pypi.org/project/maxapi-python/) — userbot-клиент MAX
  (внутренний WebSocket-протокол, импорт `pymax`).
- [`aiogram`](https://docs.aiogram.dev/) 3 — Telegram Bot API, поддержка тем-форумов.
```
