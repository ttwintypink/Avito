"""
avito/time_utils.py — Парсинг времени публикации Авито.

Авито использует относительные форматы:
  - "Только что"
  - "Сегодня, 15:30"
  - "Вчера, 09:15"
  - "2 июля, 14:00"
  - "12 декабря 2023, 08:00"

Этот модуль переводит их в datetime с учётом часового пояса пользователя.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Московское время (UTC+3) — Авито работает по Москве
MOSCOW_TZ = timezone(timedelta(hours=3))

# Месяцы для парсинга (все падежи, которые встречаются на Авито)
MONTHS_MAP: dict[str, int] = {
    "января": 1,   "январь": 1,
    "февраля": 2,  "февраль": 2,
    "марта": 3,    "март": 3,
    "апреля": 4,   "апрель": 4,
    "мая": 5,      "май": 5,
    "июня": 6,     "июнь": 6,
    "июля": 7,     "июль": 7,
    "августа": 8,  "август": 8,
    "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10,
    "ноября": 11,  "ноябрь": 11,
    "декабря": 12, "декабрь": 12,
}


def parse_avito_time(raw: str) -> Optional[datetime]:
    """
    Перевести строку времени Авито в datetime (MSK).

    Поддерживаемые форматы:
      - "Только что"          → сейчас
      - "1 минуту назад"      → now - 1 min
      - "5 минут назад"       → now - 5 min
      - "Сегодня, 15:30"      → сегодня 15:30
      - "Вчера, 09:15"        → вчера 09:15
      - "2 июля, 14:00"       → 2 июля текущего года
      - "12 декабря 2023"     → точная дата

    Args:
        raw: Строка времени с Авито (может содержать лишние пробелы).

    Returns:
        datetime с таймзоной MSK или None при ошибке парсинга.
    """
    if not raw:
        return None

    text = raw.strip()
    now = datetime.now(tz=MOSCOW_TZ)

    # ── "Только что" ──
    if text.lower().startswith("только что"):
        return now

    # ── "N минут(ы) назад" ──
    minutes_ago_match = re.match(
        r"(\d+)\s*минут[уы]?\s*назад", text, re.IGNORECASE
    )
    if minutes_ago_match:
        minutes = int(minutes_ago_match.group(1))
        return now - timedelta(minutes=minutes)

    # ── "N час(ов/а) назад" ──
    hours_ago_match = re.match(
        r"(\d+)\s*час[аов]?\s*назад", text, re.IGNORECASE
    )
    if hours_ago_match:
        hours = int(hours_ago_match.group(1))
        return now - timedelta(hours=hours)

    # ── "Сегодня, HH:MM" ──
    today_match = re.match(
        r"Сегодня,?\s*(\d{1,2}):(\d{2})", text, re.IGNORECASE
    )
    if today_match:
        hour = int(today_match.group(1))
        minute = int(today_match.group(2))
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # ── "Вчера, HH:MM" ──
    yesterday_match = re.match(
        r"Вчера,?\s*(\d{1,2}):(\d{2})", text, re.IGNORECASE
    )
    if yesterday_match:
        hour = int(yesterday_match.group(1))
        minute = int(yesterday_match.group(2))
        yesterday = now - timedelta(days=1)
        return yesterday.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

    # ── "D month, HH:MM" (например, "2 июля, 14:00") ──
    month_time_match = re.match(
        r"(\d{1,2})\s+(\w+),?\s*(\d{1,2}):(\d{2})", text, re.IGNORECASE
    )
    if month_time_match:
        day = int(month_time_match.group(1))
        month_name = month_time_match.group(2).lower()
        hour = int(month_time_match.group(3))
        minute = int(month_time_match.group(4))

        month_num = MONTHS_MAP.get(month_name)
        if month_num:
            try:
                dt = datetime(
                    year=now.year, month=month_num, day=day,
                    hour=hour, minute=minute, tzinfo=MOSCOW_TZ,
                )
                # Если дата в будущем — значит прошлогодний
                if dt > now:
                    dt = dt.replace(year=now.year - 1)
                return dt
            except ValueError:
                pass

    # ── "D month YYYY" (например, "12 декабря 2023") ──
    month_year_match = re.match(
        r"(\d{1,2})\s+(\w+)\s+(\d{4})", text, re.IGNORECASE
    )
    if month_year_match:
        day = int(month_year_match.group(1))
        month_name = month_year_match.group(2).lower()
        year = int(month_year_match.group(3))

        month_num = MONTHS_MAP.get(month_name)
        if month_num:
            try:
                return datetime(
                    year=year, month=month_num, day=day,
                    hour=0, minute=0, tzinfo=MOSCOW_TZ,
                )
            except ValueError:
                pass

    # ── "D month" (без времени, без года) ──
    month_only_match = re.match(
        r"(\d{1,2})\s+(\w+)", text, re.IGNORECASE
    )
    if month_only_match:
        day = int(month_only_match.group(1))
        month_name = month_only_match.group(2).lower()
        month_num = MONTHS_MAP.get(month_name)
        if month_num:
            try:
                dt = datetime(
                    year=now.year, month=month_num, day=day,
                    hour=0, minute=0, tzinfo=MOSCOW_TZ,
                )
                if dt > now:
                    dt = dt.replace(year=now.year - 1)
                return dt
            except ValueError:
                pass

    # ── ISO-формат (если пришёл из JSON) ──
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        pass

    logger.warning("Не удалось распарсить время Авито: '%s'", text)
    return None


def format_avito_time(dt: Optional[datetime]) -> str:
    """
    Форматировать datetime в читаемую строку для Telegram-сообщения.

    Examples:
      "Сегодня, 15:30"
      "Вчера, 09:15"
      "5 июля, 14:00"
    """
    if dt is None:
        return "Неизвестно"

    now = datetime.now(tz=MOSCOW_TZ)
    dt_local = dt.astimezone(MOSCOW_TZ)

    time_str = dt_local.strftime("%H:%M")

    if dt_local.date() == now.date():
        return f"Сегодня, {time_str}"

    yesterday = (now - timedelta(days=1)).date()
    if dt_local.date() == yesterday:
        return f"Вчера, {time_str}"

    return dt_local.strftime("%d.%m.%Y, %H:%M")
