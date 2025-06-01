# Notion-to-Telegram Sync Bot

Этот бот синхронизирует страницы из Notion в закреплённые сообщения Telegram-канала/чата, поддерживает форматирование MarkdownV2, корректно обрабатывает таблицы, списки, заголовки, спойлеры, ссылки, никнеймы, и ведёт служебную базу данных Notion с датами последних обновлений всех постов.

---

## Возможности

- Автоматический экспорт страниц из Notion в Telegram.
- Поддержка форматирования MarkdownV2 (жирный, курсив, зачёркнутый, спойлер, ссылки и др.).
- Корректное экранирование всех спецсимволов, включая списки, заголовки, цитаты, никнеймы.
- Таблицы отображаются как code/pre-блоки для лучшей читаемости.
- Toggle-блоки Notion превращаются в спойлеры Telegram.
- В служебной базе Notion отображаются все посты с датами последних обновлений.
- Голосования (опросы) в пинах Telegram не трогаются.
- Поддержка pinned сообщений, логирование ошибок, автоматическое создание и обновление сообщений.
- Асинхронная работа на базе python-telegram-bot.

---

## Требования

- Python 3.9+
- [python-telegram-bot](https://python-telegram-bot.org) >= 20
- [notion-client](https://github.com/ramnes/notion-sdk-py)
- [python-dotenv](https://pypi.org/project/python-dotenv/)

---

## Быстрый старт

### 1. Клонируйте репозиторий

git clone <your_repo_url>
cd <your_repo_folder>

text

### 2. Создайте виртуальное окружение

python3 -m venv venv
source venv/bin/activate # для Linux/Mac
venv\Scripts\activate # для Windows

text

### 3. Установите зависимости

pip install -r requirements.txt

text

Пример содержимого `requirements.txt`:

python-telegram-bot>=20
notion-client
python-dotenv

text

### 4. Настройте переменные окружения

Создайте файл `.env` в корне проекта и заполните его:

NOTION_API_KEY=секретный_ключ_интеграции_Notion
NOTION_ROOT_PAGE_URL=https://www.notion.so/your_root_page_id
TELEGRAM_BOT_TOKEN=ваш_токен_бота
TELEGRAM_CHAT_ID=-1001234567890 # ID вашего чата/канала
SYNC_INTERVAL_SECONDS=300 # интервал синхронизации в секундах
TIMEZONE=Europe/Moscow # ваш часовой пояс

text

- Получить токен Telegram-бота: [BotFather](https://t.me/BotFather)
- Получить интеграционный ключ Notion: [Инструкция](https://developers.notion.com/docs/create-a-notion-integration)
- Узнать chat_id можно через [@userinfobot](https://t.me/userinfobot) или [@getmyid_bot](https://t.me/getmyid_bot).

### 5. Запустите бота

python main.py

text

---

## Структура проекта

.
├── main.py
├── requirements.txt
├── .env
├── pinned_messages.json
└── README.md

text

---

## Особенности работы

- **Служебная база данных в Notion**: создаётся автоматически, содержит все посты с датами последних обновлений и ссылками на сообщения в Telegram.
- **Посты в Telegram**: обновляются только при изменении страницы в Notion, но в базе фиксируются все страницы.
- **Pinned polls (опросы)**: бот не трогает закреплённые голосования в чате.
- **Таблицы**: выводятся как code/pre-блоки для лучшей читабельности.
- **Toggle-блоки**: превращаются в Telegram-спойлеры (`||текст||`).
- **Логирование**: ошибки и проблемные сообщения сохраняются в файл `error_<page_id>.txt`.

---

## Полезные ссылки

- [Документация python-telegram-bot](https://docs.python-telegram-bot.org/)
- [Документация Notion API](https://developers.notion.com/)
- [О MarkdownV2 в Telegram](https://core.telegram.org/bots/api#markdownv2-style)
- [Ограничения Telegram Markdown](https://core.telegram.org/bots/api#formatting-options)

---

## Советы

- Не используйте Markdown-заголовки (`# Heading`), используйте жирный текст (`*Heading*`).
- Для списков экранируйте дефис (`\- item`) и точку (`1\. item`).
- Для таблиц используйте только code/pre-блоки.
- Для спойлеров используйте `||текст||`.
- Не экранируйте URL в ссылках, только текст.

---

## Контакты и поддержка

Если у вас возникли вопросы или нужна помощь — создайте issue или напишите автору.

---
