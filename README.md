# Avito + TG Username Finder Bot

Мульти-режимный Telegram-бот с двумя функциями:
1. **Avito-парсер** — поиск объявлений на Авито (Playwright + stealth)
2. **TG Username Finder** — поиск красивых свободных юзернеймов (Pyrogram + Fragment)

## Установка

```bash
pip install -r requirements.txt
playwright install chromium
```

## Настройка

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
```

Обязательные переменные:
- `BOT_TOKEN` — токен Telegram-бота (от @BotFather)
- `ADMIN_ID` — ваш Telegram ID
- `AUTH_KEY_HEX` — 512 hex-символов авторизационного ключа Pyrogram
- `DC_ID` — номер DC (обычно 1-5)

## Запуск

```bash
python main.py
```

## Команды

- `/start` — приветствие
- `/avito` — режим парсера Авито
- `/tg` — режим поиска юзернеймов

## Режим генерации юзернеймов

- **Random** — чередование гласных/согласных (читаемые комбинации)
- **Premium** — словарь + брендовые паттерны (CVCV, VCVC, CVCVCV)

## Технологии

- Aiogram 3.x (Telegram Bot API)
- Pyrogram (MTProto UserBot)
- Playwright + playwright-stealth (Avito)
- aiosqlite (WAL-режим)
- APScheduler (фоновые задачи)
- aiohttp (Fragment.com)
