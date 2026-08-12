"""
handlers/avito.py — Хендлеры режима Авито.

Функционал:
  - Настройка фильтров (keyword, category, min/max цена) через FSM
  - Запуск / остановка фонового парсинга (APScheduler)
  - Статус парсера
  - Отправка найденных объявлений в Telegram
  - Админ-команды: /parser_start, /parser_stop, /parser_status
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database
from avito.parser import AvitoParser, AvitoAd
from avito.keyboards import (
    ad_keyboard,
    avito_filter_keyboard,
    avito_mode_keyboard,
    parser_status_keyboard,
)
from config import ADMIN_ID, AVITO_PARSE_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

router = Router(name="avito")


# ──────────────────────────────────────────────
#  FSM — состояния настройки фильтров
# ──────────────────────────────────────────────

class AvitoFilterStates(StatesGroup):
    waiting_keyword = State()
    waiting_category = State()
    waiting_min_price = State()
    waiting_max_price = State()


# ──────────────────────────────────────────────
#  Callback: Настроить фильтры
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_filters")
async def cb_filters_menu(callback: CallbackQuery) -> None:
    """Показать меню настройки фильтров."""
    try:
        await callback.message.edit_text(
            "⚙️ <b>Настройка фильтров Авито</b>\n\n"
            "Выберите параметр для изменения:",
            parse_mode=ParseMode.HTML,
            reply_markup=avito_filter_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка avito_filters: %s", exc)
    await callback.answer()


# ──────────────────────────────────────────────
#  Callback: Установка ключевого слова
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_set_keyword")
async def cb_set_keyword(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать ввод ключевого слова."""
    await state.set_state(AvitoFilterStates.waiting_keyword)
    await callback.message.edit_text(
        "🔑 <b>Введите ключевое слово для поиска</b>\n"
        "(например: <code>i5-13400F</code>)\n\n"
        "Для отмены нажмите /cancel",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.message(AvitoFilterStates.waiting_keyword)
async def process_keyword(message: Message, state: FSMContext, db: Database) -> None:
    """Сохранить ключевое слово."""
    user_id = message.from_user.id
    keyword = message.text.strip()

    if not keyword:
        await message.answer("❌ Ключевое слово не может быть пустым. Попробуйте снова:")
        return

    try:
        await db.set_filters(user_id, keyword=keyword)
        await state.clear()
        await message.answer(
            f"✅ Ключевое слово: <b>{keyword}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=avito_mode_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка сохранения keyword: %s", exc)
        await message.answer("❌ Ошибка сохранения.")


# ──────────────────────────────────────────────
#  Callback: Установка категории
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_set_category")
async def cb_set_category(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать ввод категории."""
    await state.set_state(AvitoFilterStates.waiting_category)
    await callback.message.edit_text(
        "📁 <b>Введите категорию Авито</b>\n"
        "(например: <code>elektronika</code>, <code>personalnye_kompyutery</code>)\n\n"
        "Или отправьте <code>0</code> чтобы сбросить категорию.\n"
        "Для отмены: /cancel",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.message(AvitoFilterStates.waiting_category)
async def process_category(message: Message, state: FSMContext, db: Database) -> None:
    """Сохранить категорию."""
    user_id = message.from_user.id
    category = message.text.strip()

    try:
        if category == "0":
            await db.set_filters(user_id, category=None)
            await message.answer("✅ Категория сброшена.", reply_markup=avito_mode_keyboard())
        else:
            await db.set_filters(user_id, category=category)
            await message.answer(
                f"✅ Категория: <b>{category}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=avito_mode_keyboard(),
            )
        await state.clear()
    except Exception as exc:
        logger.error("Ошибка сохранения category: %s", exc)
        await message.answer("❌ Ошибка сохранения.")


# ──────────────────────────────────────────────
#  Callback: Установка мин/макс цены
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_set_min_price")
async def cb_set_min_price(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать ввод мин. цены."""
    await state.set_state(AvitoFilterStates.waiting_min_price)
    await callback.message.edit_text(
        "💰 <b>Введите минимальную цену</b> (в рублях)\n\n"
        "Отправьте <code>0</code> чтобы сбросить.\n"
        "Для отмены: /cancel",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.message(AvitoFilterStates.waiting_min_price)
async def process_min_price(message: Message, state: FSMContext, db: Database) -> None:
    """Сохранить мин. цену."""
    user_id = message.from_user.id

    try:
        value = int(message.text.strip())
        min_price = None if value == 0 else value
        await db.set_filters(user_id, min_price=min_price)
        await state.clear()
        text = "✅ Мин. цена сброшена." if min_price is None else f"✅ Мин. цена: <b>{min_price} ₽</b>"
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=avito_mode_keyboard())
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:")
    except Exception as exc:
        logger.error("Ошибка сохранения min_price: %s", exc)
        await message.answer("❌ Ошибка сохранения.")


@router.callback_query(F.data == "avito_set_max_price")
async def cb_set_max_price(callback: CallbackQuery, state: FSMContext) -> None:
    """Начать ввод макс. цены."""
    await state.set_state(AvitoFilterStates.waiting_max_price)
    await callback.message.edit_text(
        "💰 <b>Введите максимальную цену</b> (в рублях)\n\n"
        "Отправьте <code>0</code> чтобы сбросить.\n"
        "Для отмены: /cancel",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.message(AvitoFilterStates.waiting_max_price)
async def process_max_price(message: Message, state: FSMContext, db: Database) -> None:
    """Сохранить макс. цену."""
    user_id = message.from_user.id

    try:
        value = int(message.text.strip())
        max_price = None if value == 0 else value
        await db.set_filters(user_id, max_price=max_price)
        await state.clear()
        text = "✅ Макс. цена сброшена." if max_price is None else f"✅ Макс. цена: <b>{max_price} ₽</b>"
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=avito_mode_keyboard())
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:")
    except Exception as exc:
        logger.error("Ошибка сохранения max_price: %s", exc)
        await message.answer("❌ Ошибка сохранения.")


# ──────────────────────────────────────────────
#  Callback: Сбросить фильтры
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_clear_filters")
async def cb_clear_filters(callback: CallbackQuery, db: Database) -> None:
    """Сбросить все фильтры."""
    user_id = callback.from_user.id
    try:
        await db.clear_filters(user_id)
        await callback.message.edit_text(
            "🗑 <b>Все фильтры сброшены.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=avito_mode_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка clear_filters: %s", exc)
    await callback.answer()


# ──────────────────────────────────────────────
#  Callback: /cancel для FSM
# ──────────────────────────────────────────────

@router.message(Command("cancel"), StateFilter(AvitoFilterStates))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отменить ввод фильтра."""
    await state.clear()
    await message.answer(
        "❌ Ввод отменён.",
        reply_markup=avito_mode_keyboard(),
    )


# ──────────────────────────────────────────────
#  Callback: Статус парсера
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_status")
async def cb_parser_status(callback: CallbackQuery, avito_parser: AvitoParser) -> None:
    """Показать статус парсера Авито."""
    try:
        stats = avito_parser.stats
        text = (
            "📊 <b>Статус парсера Авито</b>\n\n"
            f"🔄 Запущен: <b>{'Да' if stats['is_running'] else 'Нет'}</b>\n"
            f"⏸ На паузе (капча): <b>{'Да' if stats['is_paused'] else 'Нет'}</b>\n"
            f"🌐 Браузер: <b>{'Жив' if stats['browser_alive'] else 'Не запущен'}</b>\n"
            f"📋 Обработано: <b>{stats['total_parsed']}</b>\n"
            f"📨 Отправлено: <b>{stats['total_sent']}</b>\n"
            f"⏰ Последний парс: <b>{stats['last_parse']}</b>"
        )
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=parser_status_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка avito_status: %s", exc)
    await callback.answer()


# ──────────────────────────────────────────────
#  Callback: Запуск / остановка парсинга
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_parser_start")
async def cb_parser_start(
    callback: CallbackQuery,
    db: Database,
    avito_parser: AvitoParser,
    scheduler: AsyncIOScheduler,
) -> None:
    """Запустить фоновый парсинг Авито через APScheduler."""
    user_id = callback.from_user.id

    try:
        # Проверяем, есть ли фильтры
        filters = await db.get_filters(user_id)
        if not filters or not filters["keyword"]:
            await callback.answer("⚠️ Сначала задайте ключевое слово!", show_alert=True)
            return

        # Запускаем браузер если не запущен
        if not avito_parser.is_running and not avito_parser.stats["browser_alive"]:
            await avito_parser.launch()

        # Помечаем в БД
        await db.set_parser_running(True)

        # Добавляем задачу в APScheduler
        job_id = f"avito_parse_{user_id}"
        if not scheduler.get_job(job_id):
            scheduler.add_job(
                _avito_parse_job,
                "interval",
                seconds=AVITO_PARSE_INTERVAL_SECONDS,
                id=job_id,
                args=[user_id, db, avito_parser],
                replace_existing=True,
            )

        await callback.message.edit_text(
            "▶️ <b>Парсинг Авито запущен!</b>\n\n"
            f"Интервал: каждые {AVITO_PARSE_INTERVAL_SECONDS} сек.\n"
            f"Ключевое слово: <code>{filters['keyword']}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=parser_status_keyboard(),
        )
        logger.info("Парсинг Авито запущен для user_id=%d", user_id)

    except Exception as exc:
        logger.error("Ошибка запуска парсинга: %s", exc)
        await callback.answer("❌ Ошибка запуска.", show_alert=True)


@router.callback_query(F.data == "avito_parser_stop")
async def cb_parser_stop(
    callback: CallbackQuery,
    db: Database,
    avito_parser: AvitoParser,
    scheduler: AsyncIOScheduler,
) -> None:
    """Остановить фоновый парсинг Авито."""
    user_id = callback.from_user.id

    try:
        await db.set_parser_running(False)

        # Удаляем задачу из APScheduler
        job_id = f"avito_parse_{user_id}"
        scheduler.remove_job(job_id)

        await callback.message.edit_text(
            "⏹ <b>Парсинг Авито остановлен.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=avito_mode_keyboard(),
        )
        logger.info("Парсинг Авито остановлен для user_id=%d", user_id)

    except Exception as exc:
        logger.error("Ошибка остановки парсинга: %s", exc)
        await callback.answer("❌ Ошибка остановки.", show_alert=True)


# ──────────────────────────────────────────────
#  Админ-команды
# ──────────────────────────────────────────────

@router.message(Command("parser_start"))
async def admin_parser_start(
    message: Message,
    db: Database,
    avito_parser: AvitoParser,
    scheduler: AsyncIOScheduler,
) -> None:
    """Админ: /parser_start — запустить парсинг."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админа.")
        return

    # Делегируем логику уже написанному callback-хендлеру
    try:
        filters = await db.get_filters(message.from_user.id)
        if not filters or not filters["keyword"]:
            await message.answer("⚠️ Сначала задайте ключевое слово через /avito → Настроить фильтры.")
            return

        if not avito_parser.stats["browser_alive"]:
            await avito_parser.launch()

        await db.set_parser_running(True)

        job_id = f"avito_parse_{message.from_user.id}"
        scheduler.add_job(
            _avito_parse_job,
            "interval",
            seconds=AVITO_PARSE_INTERVAL_SECONDS,
            id=job_id,
            args=[message.from_user.id, db, avito_parser],
            replace_existing=True,
        )

        await message.answer(
            "▶️ <b>Парсинг запущен (админ).</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Ошибка /parser_start: %s", exc)
        await message.answer("❌ Ошибка запуска.")


@router.message(Command("parser_stop"))
async def admin_parser_stop(
    message: Message,
    db: Database,
    avito_parser: AvitoParser,
    scheduler: AsyncIOScheduler,
) -> None:
    """Админ: /parser_stop — остановить парсинг."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админа.")
        return

    try:
        await db.set_parser_running(False)
        job_id = f"avito_parse_{message.from_user.id}"
        scheduler.remove_job(job_id)
        await message.answer("⏹ <b>Парсинг остановлен (админ).</b>", parse_mode=ParseMode.HTML)
    except Exception as exc:
        logger.error("Ошибка /parser_stop: %s", exc)


@router.message(Command("parser_status"))
async def admin_parser_status(message: Message, avito_parser: AvitoParser) -> None:
    """Админ: /parser_status — статус парсера."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админа.")
        return

    stats = avito_parser.stats
    await message.answer(
        f"📊 <b>Статус парсера</b>\n\n"
        f"🔄 Запущен: {'Да' if stats['is_running'] else 'Нет'}\n"
        f"⏸ Пауза (капча): {'Да' if stats['is_paused'] else 'Нет'}\n"
        f"🌐 Браузер: {'Жив' if stats['browser_alive'] else 'Нет'}\n"
        f"📋 Обработано: {stats['total_parsed']}\n"
        f"📨 Отправлено: {stats['total_sent']}\n"
        f"⏰ Последний парс: {stats['last_parse']}",
        parse_mode=ParseMode.HTML,
    )


# ──────────────────────────────────────────────
#  APScheduler Job — фоновый парсинг Авито
# ──────────────────────────────────────────────

async def _avito_parse_job(
    user_id: int,
    db: Database,
    avito_parser: AvitoParser,
) -> None:
    """
    Задача APScheduler: запускает один цикл парсинга Авито.

    Найденные объявления отправляются через bot.send_photo.
    """
    from aiogram import Bot
    from config import BOT_TOKEN

    bot = Bot(token=BOT_TOKEN)

    try:
        filters = await db.get_filters(user_id)
        if not filters or not filters["keyword"]:
            logger.warning("Нет фильтров для user_id=%d, пропускаем.", user_id)
            return

        keyword = filters["keyword"]
        category = filters["category"]
        min_price = filters["min_price"]
        max_price = filters["max_price"]

        logger.info("APScheduler: парсинг Авито для user_id=%d, keyword='%s'", user_id, keyword)

        new_ads = await avito_parser.parse(
            user_id=user_id,
            keyword=keyword,
            category=category,
            min_price=min_price,
            max_price=max_price,
        )

        # Отправляем каждое объявление
        for ad in new_ads:
            try:
                if ad.first_photo:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=ad.first_photo,
                        caption=ad.format_caption(),
                        parse_mode=ParseMode.HTML,
                        reply_markup=ad_keyboard(ad.url),
                    )
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=ad.format_caption(),
                        parse_mode=ParseMode.HTML,
                        reply_markup=ad_keyboard(ad.url),
                    )

                await db.mark_ad_sent(user_id, ad.ad_id)
                avito_parser._total_sent += 1

            except TelegramBadRequest as tba:
                logger.warning("Telegram ошибка отправки: %s", tba)
            except Exception as exc:
                logger.error("Ошибка отправки объявления %s: %s", ad.ad_id, exc)

        if new_ads:
            logger.info("Отправлено %d новых объявлений для user_id=%d", len(new_ads), user_id)

    except Exception as exc:
        logger.error("Ошибка _avito_parse_job: %s", exc)
    finally:
        await bot.session.close()
