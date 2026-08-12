"""
config.py — Центральный конфигурационный модуль бота.

Все секреты и настраиваемые параметры загружаются отсюда.
В production следует использовать python-dotenv или переменные окружения.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
#  Telegram Bot API
# ──────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

# ──────────────────────────────────────────────
#  Pyrogram (UserBot) — MTProto авторизация через AUTH_KEY
# ──────────────────────────────────────────────
# Вместо API_ID + API_HASH + интерактивного входа (номер/код)
# используем готовый ключ авторизации (hex) и номер DC.
# AUTH_KEY_HEX можно экспортировать из существующей сессии Pyrogram/Telethon.
AUTH_KEY_HEX: str = os.getenv("AUTH_KEY_HEX", "")
DC_ID: int = int(os.getenv("DC_ID", "2"))  # 2=DC2 по умолчанию (Европа)
PYROGRAM_SESSION: str = os.getenv("PYROGRAM_SESSION", "userbot_session")

# ──────────────────────────────────────────────
#  Avito Parser
# ──────────────────────────────────────────────
# Папка для persistent-контекста Playwright (куки, localStorage)
AVITO_PROFILE_DIR: Path = Path(__file__).parent / "avito_profile"

# Город по умолчанию и регион доставки
DEFAULT_CITY: str = "Смоленск"
DEFAULT_DELIVERY_CITY: str = "Смоленск"

# Базовый URL Авито (поиск)
AVITO_BASE_URL: str = "https://www.avito.ru"

# Параметр сортировки: s=104 → «Сначала новые по дате»
AVITO_SORT_PARAM: str = "s=104"

# Антибан: диапазоны задержек (секунды)
AVITO_MIN_DELAY: float = 5.0
AVITO_MAX_DELAY: float = 12.0
AVITO_SCROLL_MIN: int = 500
AVITO_SCROLL_MAX: int = 1500

# Интервал фонового парсинга (секунды)
AVITO_PARSE_INTERVAL_SECONDS: int = 300  # 5 минут

# Максимальная длина описания в сообщении
AVITO_MAX_DESCRIPTION_LENGTH: int = 300

# ──────────────────────────────────────────────
#  TG Username Search
# ──────────────────────────────────────────────
# Диапазон длин юзернеймов по умолчанию
TG_MIN_LENGTH_DEFAULT: int = 5
TG_MAX_LENGTH_DEFAULT: int = 7

# Размер батча для asyncio.gather
TG_BATCH_SIZE: int = 50

# Задержка между батчами для защиты от FloodWait (секунды)
TG_BATCH_DELAY: float = 2.0

# Интервал фонового поиска (секунды)
TG_SEARCH_INTERVAL_SECONDS: int = 60

# Fragment URL
FRAGMENT_BASE_URL: str = "https://fragment.com/username"

# ──────────────────────────────────────────────
#  Database
# ──────────────────────────────────────────────
DB_PATH: Path = Path(__file__).parent / "bot_database.db"

# ──────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(funcName)-25s | %(message)s"
)
