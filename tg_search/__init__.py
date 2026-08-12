"""
tg_search — модуль поиска красивых свободных юзернеймов.

Публичный интерфейс:
    from tg_search import UsernameFinder, UsernameResult, UsernameStatus, create_pyrogram_client
"""

from .username_finder import (
    FragmentChecker,
    TelegramChecker,
    UsernameFinder,
    UsernameGenerator,
    UsernameResult,
    UsernameStatus,
    create_pyrogram_client,
)
from .keyboards import (
    found_username_keyboard,
    tg_length_keyboard,
    tg_mode_keyboard,
    tg_running_keyboard,
)

__all__ = [
    # Оркестратор
    "UsernameFinder",
    # Компоненты
    "UsernameGenerator",
    "TelegramChecker",
    "FragmentChecker",
    "UsernameResult",
    "UsernameStatus",
    # Фабрика
    "create_pyrogram_client",
    # Клавиатуры
    "tg_mode_keyboard",
    "tg_length_keyboard",
    "found_username_keyboard",
    "tg_running_keyboard",
]
