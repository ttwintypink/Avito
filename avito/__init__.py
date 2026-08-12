"""
avito — модуль парсера объявлений Авито (Playwright).

Публичный интерфейс:
    from avito import AvitoParser, AvitoAd, CaptchaDetector
"""

from .parser import AvitoAd, AvitoParser, CaptchaDetector
from .keyboards import (
    ad_keyboard,
    avito_filter_keyboard,
    avito_mode_keyboard,
    parser_status_keyboard,
)
from .time_utils import format_avito_time, parse_avito_time

__all__ = [
    # Парсер
    "AvitoParser",
    "AvitoAd",
    "CaptchaDetector",
    # Клавиатуры
    "avito_mode_keyboard",
    "avito_filter_keyboard",
    "ad_keyboard",
    "parser_status_keyboard",
    # Утилиты времени
    "parse_avito_time",
    "format_avito_time",
]
