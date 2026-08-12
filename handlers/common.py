"""
handlers/common.py — Общие хендлеры: /start, /avito, /tg.

Отвечают за:
  - Приветствие и регистрацию пользователя в БД
  - Переключение режимов (avito / tg)
  - Отображение соответствующей клавиатуры
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from database import Database
from utils.helpers import is_admin

from avito.keyboards import avito_mode_keyboard
from tg_search.keyboards import tg_mode_keyboard

logger = logging.getLogger(__name__)

router = Router(name="common")


# ──────────────────────────────────────────────
#  /start
# ──────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    """Приветствие + регистрация пользователя."""
    user_id = message.from_user.id

    try:
        await db.ensure_user(user_id)
        mode = await db.get_user_mode(user_id) or "avito"

        text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            f"Я мульти-режимный бот с двумя функциями:\n"
            f"🛒 <b>Авито-парсер</b> — поиск объявлений по фильтрам\n"
            f"✨ <b>TG-поиск</b> — поиск красивых свободных юзернеймов\n\n"
            f"Текущий режим: <b>{'Авито' if mode == 'avito' else 'TG-поиск'}</b>\n\n"
            f"Используй команды:\n"
            f"  /avito — переключиться на парсер Авито\n"
            f"  /tg    — переключиться на поиск юзов"
        )

        await message.answer(text, parse_mode=ParseMode.HTML)
        logger.info("Новый пользователь: %d", user_id)

    except Exception as exc:
        logger.error("Ошибка /start для %d: %s", user_id, exc)
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


# ──────────────────────────────────────────────
#  /avito — переключение на режим Авито
# ──────────────────────────────────────────────

@router.message(Command("avito"))
async def cmd_avito(message: Message, db: Database) -> None:
    """Переключить пользователя на режим Авито."""
    user_id = message.from_user.id

    try:
        await db.ensure_user(user_id)
        await db.set_user_mode(user_id, "avito")

        text = (
            "🛒 <b>ВЫ ПЕРЕКЛЮЧЕНЫ НА ПАРСЕР АВИТО</b>\n\n"
            "Используйте кнопки для взаимодействия с панелью."
        )

        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=avito_mode_keyboard(),
        )
        logger.info("Пользователь %d → режим Авито", user_id)

    except Exception as exc:
        logger.error("Ошибка /avito: %s", exc)
        await message.answer("❌ Ошибка переключения режима.")


# ──────────────────────────────────────────────
#  /tg — переключение на режим TG-поиска
# ──────────────────────────────────────────────

@router.message(Command("tg"))
async def cmd_tg(message: Message, db: Database) -> None:
    """Переключить пользователя на режим TG-поиска."""
    user_id = message.from_user.id

    try:
        await db.ensure_user(user_id)
        await db.set_user_mode(user_id, "tg")

        text = (
            "✨ <b>ВЫ ПЕРЕКЛЮЧЕНЫ НА ПАРСЕР ЮЗОВ ТГ</b>\n\n"
            "Используйте кнопки для взаимодействия с панелью."
        )

        # Читаем gen_mode из настроек
        settings = await db.get_tg_settings(user_id)
        gen_mode = settings["gen_mode"] if settings else "random"

        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(gen_mode),
        )
        logger.info("Пользователь %d → режим TG", user_id)

    except Exception as exc:
        logger.error("Ошибка /tg: %s", exc)
        await message.answer("❌ Ошибка переключения режима.")


# ──────────────────────────────────────────────
#  Callback: возврат в меню режима
# ──────────────────────────────────────────────

@router.callback_query(F.data == "avito_back")
async def cb_avito_back(callback: CallbackQuery, db: Database) -> None:
    """Вернуться в главное меню Авито."""
    try:
        await callback.message.edit_text(
            "🛒 <b>Парсер Авито</b>\n\nИспользуйте кнопки для взаимодействия с панелью.",
            parse_mode=ParseMode.HTML,
            reply_markup=avito_mode_keyboard(),
        )
    except Exception as exc:
        logger.error("Ошибка avito_back: %s", exc)
    await callback.answer()


@router.callback_query(F.data == "tg_back")
async def cb_tg_back(callback: CallbackQuery, db: Database) -> None:
    """Вернуться в главное меню TG."""
    try:
        settings = await db.get_tg_settings(callback.from_user.id)
        gen_mode = settings["gen_mode"] if settings else "random"
        await callback.message.edit_text(
            "✨ <b>Парсер юзов TG</b>\n\nИспользуйте кнопки для взаимодействия с панелью.",
            parse_mode=ParseMode.HTML,
            reply_markup=tg_mode_keyboard(gen_mode),
        )
    except Exception as exc:
        logger.error("Ошибка tg_back: %s", exc)
    await callback.answer()
