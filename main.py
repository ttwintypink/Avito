"""
main.py — Точка входа мульти-режимного Telegram-бота.

Запуск:
    python main.py

Последовательность инициализации:
  1. Настройка логирования
  2. Подключение к БД + создание таблиц
  3. Инициализация Pyrogram-клиента (UserBot)
  4. Инициализация Aiogram-бота + Dispatcher + роутеры
  5. Запуск APScheduler
  6. Регистрация middleware (DI для db, parser, finder, scheduler)
  7. asyncio.gather(bot polling, pyrogram idle)

Graceful shutdown:
  Ctrl+C → закрываем parser, finder, БД, scheduler, pyrogram
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Awaitable, Callable, Dict

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from pyrogram import Client as PyrogramClient

from config import (
    ADMIN_ID,
    AUTH_KEY_HEX,
    DC_ID,
    BOT_TOKEN,
    PYROGRAM_SESSION,
    TG_MAX_LENGTH_DEFAULT,
    TG_MIN_LENGTH_DEFAULT,
)
from database import Database
from utils.helpers import is_admin, setup_logging

from avito.parser import AvitoParser
from tg_search.username_finder import UsernameFinder, create_pyrogram_client

# Хендлеры
from handlers.common import router as common_router
from handlers.avito import router as avito_router
from handlers.tg import router as tg_router

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  DI Middleware — прокидывание зависимостей
# ──────────────────────────────────────────────

class DIMiddleware:
    """
    Простое DI-решение: прокидывает общие объекты (db, avito_parser,
    username_finder, scheduler) в хендлеры через kwargs.

    Aiogram 3 поддерживает dependency injection через
    dispatcher.update.middleware или через router-kwargs.
    """

    def __init__(
        self,
        db: Database,
        avito_parser: AvitoParser,
        username_finder: UsernameFinder,
        scheduler: AsyncIOScheduler,
    ) -> None:
        self._db = db
        self._avito_parser = avito_parser
        self._username_finder = username_finder
        self._scheduler = scheduler

    def inject(self, dispatcher: Dispatcher) -> None:
        """Зарегистрировать зависимости в dispatcher."""
        # Aiogram 3: передаём через workflow_data
        dispatcher["db"] = self._db
        dispatcher["avito_parser"] = self._avito_parser
        dispatcher["username_finder"] = self._username_finder
        dispatcher["scheduler"] = self._scheduler


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

async def main() -> None:
    """Главная асинхронная точка входа."""

    # ═══════════════════════════════════════════
    #  1. Логирование
    # ═══════════════════════════════════════════
    setup_logging()
    logger.info("=" * 60)
    logger.info("МУЛЬТИ-РЕЖИМНЫЙ TELEGRAM-БОТ ЗАПУСКАЕТСЯ")
    logger.info("=" * 60)

    # ═══════════════════════════════════════════
    #  2. БД
    # ═══════════════════════════════════════════
    db = Database()
    try:
        await db.connect()
        await db.create_tables()
        logger.info("✅ БД инициализирована.")
    except Exception as exc:
        logger.critical("Не удалось инициализировать БД: %s", exc)
        sys.exit(1)

    # ═══════════════════════════════════════════
    #  3. Pyrogram UserBot
    # ═══════════════════════════════════════════
    pyrogram_client = create_pyrogram_client()
    try:
        await pyrogram_client.start()
        me = await pyrogram_client.get_me()
        logger.info("✅ Pyrogram UserBot запущен: @%s (id: %d)", me.username, me.id)
    except Exception as exc:
        logger.critical("Не удалось запустить Pyrogram: %s", exc)
        logger.critical("Убедитесь, что AUTH_KEY_HEX и DC_ID заданы корректно.")
        await db.disconnect()
        sys.exit(1)

    # ═══════════════════════════════════════════
    #  4. Avito Parser (Playwright) — ленивый запуск
    # ═══════════════════════════════════════════
    # Парсер создаётся здесь, но браузер запускается
    # только при первом запросе (avito_parser.launch())
    avito_parser = AvitoParser(db=db)
    logger.info("✅ AvitoParser создан (браузер не запущен — запустится по требованию).")

    # ═══════════════════════════════════════════
    #  5. Username Finder (Pyrogram + Fragment)
    # ═══════════════════════════════════════════
    username_finder = UsernameFinder(
        pyrogram_client=pyrogram_client,
        db=db,
        min_length=TG_MIN_LENGTH_DEFAULT,
        max_length=TG_MAX_LENGTH_DEFAULT,
    )
    await username_finder.load_seen_from_db()
    logger.info("✅ UsernameFinder создан.")

    # ═══════════════════════════════════════════
    #  6. APScheduler
    # ═══════════════════════════════════════════
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.start()
    logger.info("✅ APScheduler запущен.")

    # ═══════════════════════════════════════════
    #  7. Aiogram Bot + Dispatcher
    # ═══════════════════════════════════════════
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # DI: прокидываем зависимости
    di = DIMiddleware(
        db=db,
        avito_parser=avito_parser,
        username_finder=username_finder,
        scheduler=scheduler,
    )
    di.inject(dp)

    # Регистрируем роутеры
    dp.include_router(common_router)
    dp.include_router(avito_router)
    dp.include_router(tg_router)

    logger.info("✅ Все роутеры зарегистрированы.")

    # ═══════════════════════════════════════════
    #  8. Запуск
    # ═══════════════════════════════════════════
    logger.info("=" * 60)
    logger.info("БОТ ЗАПУЩЕН. Ожидание сообщений...")
    logger.info("=" * 60)

    try:
        # Aiogram polling + Pyrogram idle — параллельно
        await asyncio.gather(
            dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
            ),
            _pyrogram_idle(pyrogram_client),
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал завершения.")
    except Exception as exc:
        logger.critical("Неожиданная ошибка: %s", exc)
    finally:
        # ═══════════════════════════════════════
        #  Graceful Shutdown
        # ═══════════════════════════════════════
        logger.info("Завершение работы...")

        try:
            scheduler.shutdown(wait=False)
            logger.info("APScheduler остановлен.")
        except Exception as exc:
            logger.error("Ошибка остановки scheduler: %s", exc)

        try:
            await avito_parser.close()
            logger.info("AvitoParser закрыт.")
        except Exception as exc:
            logger.error("Ошибка закрытия parser: %s", exc)

        try:
            await username_finder.close()
            logger.info("UsernameFinder закрыт.")
        except Exception as exc:
            logger.error("Ошибка закрытия finder: %s", exc)

        try:
            await pyrogram_client.stop()
            logger.info("Pyrogram остановлен.")
        except Exception as exc:
            logger.error("Ошибка остановки Pyrogram: %s", exc)

        try:
            await db.disconnect()
            logger.info("БД закрыта.")
        except Exception as exc:
            logger.error("Ошибка закрытия БД: %s", exc)

        logger.info("Бот остановлен.")


async def _pyrogram_idle(client: PyrogramClient) -> None:
    """
    Держим Pyrogram-клиент живым.

    Pyrogram.idle() блокирует до KeyboardInterrupt.
    В нашем случае мы просто ждём бесконечно,
    т.к. основное управление — через Aiogram.
    """
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
