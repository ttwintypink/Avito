"""
database/__init__.py — Публичный интерфейс модуля БД.

Импортируем Database как единую точку входа:
    from database import Database
"""

from .db import Database

__all__ = ["Database"]
