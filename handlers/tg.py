"""
handlers/tg.py — Хендлеры режима TG-поиска юзернеймов.

Функционал:
  - Запуск / остановка фонового поиска юзов
  - Настройка длины юзернеймов (5, 6, 7 букв)
  - Статистика найденных юзов
  - Отправка результатов в Telegram
  - Админ-команды: /tg_start, /tg_stop
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database
from tg_search.username_finder import UsernameFinder, UsernameResult, UsernameStatus
from tg_search.keyboards import (
    found_username_keyboard,
    tg_length_keyboard,
    tg_mode_keyboard,
    tg_running_keyboard,
)
from config import ADMIN_ID, TG_SEARCH_INTERVAL_SECONDS
from utils.helpers import is_admin

logger = logging.getLogger(__name__)

router = Router(name="tg_search")


# ──────────────────────────────────────────────
#  Callback: Запустить поиск
# ──────────────────────────────────────────────

@router.callback_query(F.data == "tg_start")
async def cb_tg_start(
    callback: CallbackQuery,
    db: Database,
    username_finder: UsernameFinder,
    scheduler: AsyncIOScheduler,
) -> None:
    """Запустить фоновый поиск юзернеймов."""
    user_id = callback.from_user.id

    try:
        # Получаем настройки
        settings = await db.get_tg_settings(user_id)
        min_len = settings["min_length"] if settings else 5
        max_len = settings["max_length"] if settings else 7

        await db.set_tg_running(user_id, True)

        # Добавляем задачу в APScheduler
        job_id = f"tg_search_{user_id}"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                _tg_search_job,
                "interval",
                seconds=TG_SEARCH_INTERVAL_SECONDS,
                id=job_id,
                args=[user_id, db, username_finder],
                replace_existing=True,
            )

        await callback.message.edit_text(
            f"🔍 <b>Поиск юзернеймов запущен!</b>\n\n"
            f"Диапазон длин: {min_len}-{max_len} букв\n"
            f"Интервал проверки: каждые {TG_SEARCH_INTERVAL_SECONDS} сек.",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_running_keyboard(),
        )
        logger.info("TG-поиск запущен для user_id=%d", user_id)

    except Exception as exc:
        logger.error("Ошибка tg_start: %s", exc)
        await callback.answer("❌ Ошибка запуска.", show_alert=True)


# ──────────────────────────────────────────────
#  Callback: Остановить поиск
# ──────────────────────────────────────────────

@router.callback_query(F.data == "tg_stop")
async def cb_tg_stop(
    callback: CallbackQuery,
    db: Database,
    username_finder: UsernameFinder,
    scheduler: AsyncIOScheduler,
) -> None:
    """Остановить фоновый поиск юзернеймов."""
    user_id = callback.from_user.id

    try:
        await db.set_tg_running(user_id, False)

        job_id = f"tg_search_{user_id}"
        scheduler.remove_job(job_id)

        settings = await db.get_tg_settings(user_id)
        gen_mode = settings["gen_mode"] if settings else "random"

        await callback.message.edit_text(
            "⏹ <b>Поиск юзернеймов остановлен.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(gen_mode),
        )
        logger.info("TG-поиск остановлен для user_id=%d", user_id)

    except Exception as exc:
        logger.error("Ошибка tg_stop: %s", exc)
        await callback.answer("❌ Ошибка остановки.", show_alert=True)


# ──────────────────────────────────────────────
#  Callback: Переключение режима генерации (random ↔ premium)
# ──────────────────────────────────────────────

@router.callback_query(F.data == "tg_toggle_gen_mode")
async def cb_toggle_gen_mode(
    callback: CallbackQuery,
    db: Database,
    username_finder: UsernameFinder,
) -> None:
    """Переключить gen_mode между 'random' и 'premium'."""
    user_id = callback.from_user.id

    try:
        settings = await db.get_tg_settings(user_id)
        current_mode = settings["gen_mode"] if settings else "random"

        # Переключаем
        new_mode = "premium" if current_mode == "random" else "random"
        await db.set_tg_settings(user_id, gen_mode=new_mode)

        # Обновляем генератор в UsernameFinder
        username_finder._gen_mode = new_mode

        mode_label = "💎 Красивые юзы" if new_mode == "premium" else "🔤 Набор букв"
        await callback.message.edit_text(
            f"✅ <b>Режим генерации:</b> {mode_label}\n\n"
            f"{'Слова из словаря + брендовые паттерны (CVCV, VCVCV)' if new_mode == 'premium' else 'Чередование гласных и согласных для читаемости'}",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(new_mode),
        )
        logger.info("TG gen_mode: %s → %s для user_id=%d", current_mode, new_mode, user_id)

    except Exception as exc:
        logger.error("Ошибка toggle_gen_mode: %s", exc)
        await callback.answer("❌ Ошибка переключения.", show_alert=True)


# ──────────────────────────────────────────────
#  Callback: Настроить длину юзов
# ──────────────────────────────────────────────

@router.callback_query(F.data == "tg_config_length")
async def cb_config_length(callback: CallbackQuery) -> None:
    """Показать клавиатуру настройки длины."""
    try:
        await callback.message.edit_text(
            "📏 <b>Настройка длины юзернеймов</b>\n\n"
            "Выберите диапазон длин для поиска:",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_length_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка tg_config_length: %s", exc)
    await callback.answer()


# ──────────────────────────────────────────────
#  Callback: Выбор длины
# ──────────────────────────────────────────────

_LENGTH_MAP = {
    "tg_len_5": (5, 5),
    "tg_len_6": (6, 6),
    "tg_len_7": (7, 7),
    "tg_len_5_6": (5, 6),
    "tg_len_5_7": (5, 7),
    "tg_len_6_7": (6, 7),
}


@router.callback_query(F.data.startswith("tg_len_"))
async def cb_set_length(callback: CallbackQuery, db: Database) -> None:
    """Установить диапазон длин юзернеймов."""
    user_id = callback.from_user.id
    data = callback.data

    length_range = _LENGTH_MAP.get(data)
    if not length_range:
        await callback.answer("❌ Неизвестный вариант.", show_alert=True)
        return

    min_len, max_len = length_range

    try:
        await db.set_tg_settings(user_id, min_length=min_len, max_length=max_len)

        # Получаем актуальные настройки (включая gen_mode)
        settings = await db.get_tg_settings(user_id)
        gen_mode = settings["gen_mode"] if settings else "random"

        await callback.message.edit_text(
            f"✅ <b>Диапазон длин установлен:</b> {min_len}-{max_len} букв\n\n"
            f"Теперь можно запустить поиск.",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(gen_mode),
        )
        logger.info("TG длина: %d-%d для user_id=%d", min_len, max_len, user_id)

    except Exception as exc:
        logger.error("Ошибка set_length: %s", exc)
        await callback.answer("❌ Ошибка сохранения.", show_alert=True)


# ──────────────────────────────────────────────
#  Callback: Статистика
# ──────────────────────────────────────────────

@router.callback_query(F.data == "tg_stats")
async def cb_tg_stats(callback: CallbackQuery, db: Database) -> None:
    """Показать статистику TG-поиска."""
    try:
        total = await db.get_found_usernames_count()
        settings = await db.get_tg_settings(callback.from_user.id)
        min_len = settings["min_length"] if settings else 5
        max_len = settings["max_length"] if settings else 7
        is_running = bool(settings["is_running"]) if settings else False

        await callback.message.edit_text(
            f"📊 <b>Статистика TG-поиска</b>\n\n"
            f"🔄 Запущен: <b>{'Да' if is_running else 'Нет'}</b>\n"
            f"📏 Диапазон длин: <b>{min_len}-{max_len}</b>\n"
            f"✨ Всего найдено: <b>{total}</b> юзернеймов",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(
                settings["gen_mode"] if settings else "random"
            ),
        )
    except Exception as exc:
        logger.error("Ошибка tg_stats: %s", exc)
    await callback.answer()


# ──────────────────────────────────────────────
#  Админ-команды
# ──────────────────────────────────────────────

@router.message(Command("tg_start"))
async def admin_tg_start(
    message: Message,
    db: Database,
    username_finder: UsernameFinder,
    scheduler: AsyncIOScheduler,
) -> None:
    """Админ: /tg_start — запустить поиск юзов."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админа.")
        return

    try:
        user_id = message.from_user.id
        await db.set_tg_running(user_id, True)

        job_id = f"tg_search_{user_id}"
        scheduler.add_job(
            _tg_search_job,
            "interval",
            seconds=TG_SEARCH_INTERVAL_SECONDS,
            id=job_id,
            args=[user_id, db, username_finder],
            replace_existing=True,
        )

        await message.answer(
            "🔍 <b>Поиск юзов запущен (админ).</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Ошибка /tg_start: %s", exc)
        await message.answer("❌ Ошибка запуска.")


@router.message(Command("tg_stop"))
async def admin_tg_stop(
    message: Message,
    db: Database,
    scheduler: AsyncIOScheduler,
) -> None:
    """Админ: /tg_stop — остановить поиск юзов."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админа.")
        return

    try:
        user_id = message.from_user.id
        await db.set_tg_running(user_id, False)
        job_id = f"tg_search_{user_id}"
        scheduler.remove_job(job_id)
        await message.answer(
            "⏹ <b>Поиск юзов остановлен (админ).</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Ошибка /tg_stop: %s", exc)


# ──────────────────────────────────────────────
#  APScheduler Job — фоновый поиск юзернеймов
# ──────────────────────────────────────────────

async def _tg_search_job(
    user_id: int,
    db: Database,
    username_finder: UsernameFinder,
) -> None:
    """
    Задача APScheduler: один цикл поиска юзернеймов.

    Найденные 100% свободные юзы отправляются через bot.send_message.
    """
    from aiogram import Bot
    from config import BOT_TOKEN

    bot = Bot(token=BOT_TOKEN)

    try:
        settings = await db.get_tg_settings(user_id)
        min_len = settings["min_length"] if settings else 5
        max_len = settings["max_length"] if settings else 7
        gen_mode = settings["gen_mode"] if settings else "random"

        logger.info(
            "APScheduler: TG-поиск для user_id=%d, длина %d-%d, режим: %s",
            user_id, min_len, max_len, gen_mode,
        )

        # Обновляем параметры генераторов
        username_finder._generator.min_length = min_len
        username_finder._generator.max_length = max_len
        username_finder._premium_generator.min_length = min_len
        username_finder._premium_generator.max_length = max_len
        username_finder._premium_generator._filtered_dict = [
            w for w in username_finder._premium_generator.DICTIONARY
            if w.isalpha() and w.islower() and min_len <= len(w) <= max_len
        ]
        username_finder._gen_mode = gen_mode

        # Запускаем один цикл поиска
        results = await username_finder.search_cycle(count=200)

        # Отправляем каждый найденный юз
        for result in results:
            if result.status != UsernameStatus.FREE:
                continue

            text = (
                f"✨ <b>Найден свободный юзернейм!</b>\n"
                f"🔤 <b>Юз:</b> @{result.username}\n"
                f"📏 <b>Длина:</b> {result.length} букв\n"
                f"🔗 <b>Fragment:</b> "
                f"<a href=\"{result.fragment_url}\">Проверить на Fragment</a>"
            )

            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=found_username_keyboard(result.username),
                    disable_web_page_preview=True,
                )
            except TelegramBadRequest as tba:
                logger.warning("Telegram ошибка отправки юза: %s", tba)
            except Exception as exc:
                logger.error("Ошибка отправки юза @%s: %s", result.username, exc)

        if results:
            logger.info(
                "Найдено %d свободных юзов для user_id=%d",
                len(results), user_id,
            )

    except Exception as exc:
        logger.error("Ошибка _tg_search_job: %s", exc)
    finally:
        await bot.session.close()
