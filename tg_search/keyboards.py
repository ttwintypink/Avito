"""
tg_search/keyboards.py — Inline-клавиатуры для режима поиска юзов.

Клавиатуры:
  - tg_mode_keyboard     — главное меню режима TG
  - tg_length_keyboard   — выбор длины юзернеймов
  - found_username_kb    — кнопки под найденным юзом
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def tg_mode_keyboard(gen_mode: str = "random") -> InlineKeyboardMarkup:
    """Главное меню режима TG-поиска юзернеймов."""
    gen_label = (
        "💎 Режим: Красивые юзы"
        if gen_mode == "premium"
        else "🔤 Режим: Набор букв"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Запустить поиск",
                    callback_data="tg_start",
                ),
                InlineKeyboardButton(
                    text="⚙️ Настроить длину юзов",
                    callback_data="tg_config_length",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=gen_label,
                    callback_data="tg_toggle_gen_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="tg_stats",
                ),
                InlineKeyboardButton(
                    text="⏹ Остановить поиск",
                    callback_data="tg_stop",
                ),
            ],
        ]
    )


def tg_length_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора диапазона длин юзернеймов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="5 букв",
                    callback_data="tg_len_5",
                ),
                InlineKeyboardButton(
                    text="6 букв",
                    callback_data="tg_len_6",
                ),
                InlineKeyboardButton(
                    text="7 букв",
                    callback_data="tg_len_7",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="5-6 букв",
                    callback_data="tg_len_5_6",
                ),
                InlineKeyboardButton(
                    text="5-7 букв",
                    callback_data="tg_len_5_7",
                ),
                InlineKeyboardButton(
                    text="6-7 букв",
                    callback_data="tg_len_6_7",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="tg_back",
                ),
            ],
        ]
    )


def found_username_keyboard(username: str) -> InlineKeyboardMarkup:
    """
    Inline-клавиатура под сообщением о найденном юзернейме.

    Кнопки:
      - Ссылка на Fragment (проверить/купить)
      - Ссылка на @FragmentBot в Telegram
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Перейти в @FragmentBot",
                    url="https://t.me/FragmentBot",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Проверить на Fragment",
                    url=f"https://fragment.com/username/{username}",
                ),
            ],
        ]
    )


def tg_running_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура когда поиск уже запущен."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏹ Остановить поиск",
                    callback_data="tg_stop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="tg_stats",
                ),
            ],
        ]
    )
