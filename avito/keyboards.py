"""
avito/keyboards.py — Inline-клавиатуры для режима Авито.

Клавиатуры:
  - avito_mode_keyboard    — главное меню режима Авито
  - avito_filter_keyboard  — меню настройки фильтров
  - ad_keyboard            — кнопка под объявлением (ссылка на Авито)
  - parser_status_keyboard — клавиатура статуса парсера
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def avito_mode_keyboard() -> InlineKeyboardMarkup:
    """Главное меню режима Авито-парсера."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить фильтры",
                    callback_data="avito_filters",
                ),
                InlineKeyboardButton(
                    text="📊 Статус парсера",
                    callback_data="avito_status",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Запустить парсинг",
                    callback_data="avito_parser_start",
                ),
                InlineKeyboardButton(
                    text="⏹ Остановить парсинг",
                    callback_data="avito_parser_stop",
                ),
            ],
        ]
    )


def avito_filter_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки фильтров Авито."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔑 Ключевое слово",
                    callback_data="avito_set_keyword",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📁 Категория",
                    callback_data="avito_set_category",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Мин. цена",
                    callback_data="avito_set_min_price",
                ),
                InlineKeyboardButton(
                    text="💰 Макс. цена",
                    callback_data="avito_set_max_price",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Сбросить фильтры",
                    callback_data="avito_clear_filters",
                ),
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="avito_back",
                ),
            ],
        ]
    )


def ad_keyboard(ad_url: str) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура под объявлением — кнопка-ссылка на Авито.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Открыть на Avito",
                    url=ad_url,
                ),
            ],
        ]
    )


def parser_status_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура статуса парсера."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶️ Запустить",
                    callback_data="avito_parser_start",
                ),
                InlineKeyboardButton(
                    text="⏹ Остановить",
                    callback_data="avito_parser_stop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="avito_back",
                ),
            ],
        ]
    )
