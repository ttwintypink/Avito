"""
handlers/__init__.py — Пакет хендлеров.

Все роутеры реэкспортируются для удобной регистрации в main.py:
    from handlers import common_router, avito_router, tg_router
"""

from .common import router as common_router
from .avito import router as avito_router
from .tg import router as tg_router

__all__ = ["common_router", "avito_router", "tg_router"]
