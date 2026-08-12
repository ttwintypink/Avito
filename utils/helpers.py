"""
utils/helpers.py — Общие вспомогательные функции.

Содержит:
  - setup_logging()  — единая конфигурация logging
  - is_admin()       — проверка на админа
  - truncate()       — безопасная обрезка текста
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from config import ADMIN_ID, LOG_FORMAT, LOG_LEVEL


def setup_logging() -> None:
    """
    Настроить корневой логгер с единым форматом.
    Вывод в stdout + файл bot.log.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    # ── stdout ──
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # ── файл ──
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом бота."""
    return user_id == ADMIN_ID


def truncate(text: Optional[str], max_length: int = 300) -> str:
    """Обрезать текст до max_length символов с добавлением '…'."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"
