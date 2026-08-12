"""
tg_search/username_finder.py — Генерация и проверка красивых юзернеймов.

Архитектура:
  1. UsernameGenerator — генерация читаемых комбинаций (чередование гласных/согласных)
  2. TelegramChecker    — Pyrogram UserBot: массовая проверка через resolve_username
  3. FragmentChecker    — aiohttp: проверка статуса на fragment.com
  4. UsernameFinder     — оркестратор: генерация → проверка TG → проверка Fragment
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiohttp
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    UsernameNotOccupied,
    UsernameInvalid,
    UsernameOccupied,
    PeerIdInvalid,
)

from config import (
    AUTH_KEY_HEX,
    DC_ID,
    FRAGMENT_BASE_URL,
    PYROGRAM_SESSION,
    TG_BATCH_DELAY,
    TG_BATCH_SIZE,
)
from database import Database

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Data classes
# ──────────────────────────────────────────────

class UsernameStatus(Enum):
    """Статус юзернейма после полной проверки."""
    FREE = "free"                # Свободен и в TG, и на Fragment
    TAKEN_TG = "taken_tg"        # Занят в Telegram
    TAKEN_FRAGMENT = "taken_fragment"  # Занят/на аукционе на Fragment
    INVALID = "invalid"          # Некорректный юзернейм
    ERROR = "error"              # Ошибка при проверке


@dataclass
class UsernameResult:
    """Результат проверки одного юзернейма."""
    username: str
    length: int
    status: UsernameStatus = UsernameStatus.ERROR
    fragment_url: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not self.fragment_url:
            self.fragment_url = f"{FRAGMENT_BASE_URL}/{self.username}"


# ──────────────────────────────────────────────
#  1a. PremiumGenerator — коммерчески ценные юзернеймы
# ──────────────────────────────────────────────

class PremiumGenerator:
    """
    Генератор коммерчески ценных юзернеймов ('premium' mode).

    Источники:
      1. Встроенный словарь коротких английских слов, имён,
         терминов из крипты/гейминга/финансов.
      2. Брендовые паттерны: CVCV (coza, luna), VCVC (apex, elgo),
         CVCVCV (kanova, rezimo).

    Категорически запрещён мусор вроде "xqzpqz".
    """

    VOWELS: str = "aeiouy"
    CONSONANTS: str = "bcdfghjklmnpqrstvwxz"

    # ── Словарь: короткие осмысленные слова (4-7 букв, только a-z) ──
    DICTIONARY: list[str] = [
        # Крипта / Web3
        "swap", "mint", "drop", "ape", "dapp", "fomo", "hodd",
        "pump", "node", "pool", "stak", "dao", "defi", "nft",
        "token", "chain", "wage", "vault", "yield", "bond",
        # Гейминг
        "gg", "glhf", "buff", "loot", "raid", "spawn",
        "skill", "level", "clan", "rank", "boss", "hero",
        # Имена (популярные, короткие)
        "alex", "max", "leo", "mia", "eva", "ira", "luna",
        "nora", "zoe", "kai", "rio", "ace", "ray", "jax",
        "nina", "olga", "roma", "den", "ark", "sol",
        # Финансы / бизнес
        "fund", "bank", "pay", "cash", "bid", "ask", "rate",
        "coin", "gold", "rich", "gain", "port", "alpha",
        # Общие красивые слова
        "luxe", "flux", "nova", "zero", "apex", "core",
        "bolt", "dash", "edge", "fury", "glow", "haze",
        "jazz", "keen", "link", "maze", "neon", "onyx",
        "peak", "quiz", "rift", "sage", "tide", "veil",
        "warp", "zinc", "vox", "orb", "gem", "fox",
        "echo", "cyber", "delta", "omega", "sigma", "theta",
        "prism", "spark", "blaze", "drift", "swift", "forge",
        "pulse", "storm", "quest", "noble", "royal", "vivid",
    ]

    # Убираем пустые и невалидные элементы при инициализации
    def __init__(
        self,
        min_length: int = 5,
        max_length: int = 7,
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length
        # Фильтруем словарь под текущий диапазон длин
        self._filtered_dict = [
            w for w in self.DICTIONARY
            if w.isalpha() and w.islower() and min_length <= len(w) <= max_length
        ]

    def _generate_cvcv(self) -> str:
        """CVCV паттерн (coza, luna, pika)."""
        c1 = random.choice(self.CONSONANTS)
        v1 = random.choice(self.VOWELS)
        c2 = random.choice(self.CONSONANTS)
        v2 = random.choice(self.VOWELS)
        return c1 + v1 + c2 + v2

    def _generate_vcvc(self) -> str:
        """VCVC паттерн (apex, elgo, otre)."""
        v1 = random.choice(self.VOWELS)
        c1 = random.choice(self.CONSONANTS)
        v2 = random.choice(self.VOWELS)
        c2 = random.choice(self.CONSONANTS)
        return v1 + c1 + v2 + c2

    def _generate_cvcvcv(self) -> str:
        """CVCVCV паттерн (kanova, rezimo, paludo)."""
        c1 = random.choice(self.CONSONANTS)
        v1 = random.choice(self.VOWELS)
        c2 = random.choice(self.CONSONANTS)
        v2 = random.choice(self.VOWELS)
        c3 = random.choice(self.CONSONANTS)
        v3 = random.choice(self.VOWELS)
        return c1 + v1 + c2 + v2 + c3 + v3

    def _generate_vcvcv(self) -> str:
        """VCVCV паттерн (aleno, urego, iluna)."""
        v1 = random.choice(self.VOWELS)
        c1 = random.choice(self.CONSONANTS)
        v2 = random.choice(self.VOWELS)
        c2 = random.choice(self.CONSONANTS)
        v3 = random.choice(self.VOWELS)
        return v1 + c1 + v2 + c2 + v3

    def _generate_cvvcv(self) -> str:
        """CVVCV паттерн (koolo, reemi, baako) — брендовый."""
        c1 = random.choice(self.CONSONANTS)
        v1 = random.choice(self.VOWELS)
        v2 = random.choice(self.VOWELS)
        c2 = random.choice(self.CONSONANTS)
        v3 = random.choice(self.VOWELS)
        return c1 + v1 + v2 + c2 + v3

    def _generate_one(self, target_length: int) -> str:
        """
        Сгенерировать один premium-юзернейм.

        Стратегия:
          40% — из словаря (случайный выбор)
          20% — CVCV (если длина 4)
          20% — VCVCV / CVVCV (если длина 5)
          20% — CVCVCV (если длина 6)
        """
        roll = random.random()

        # Словарь (40% шанс или фоллбэк)
        if roll < 0.40 and self._filtered_dict:
            word = random.choice(self._filtered_dict)
            if len(word) == target_length:
                return word
            # Если длина не совпадает — обрезаем/дополняем
            if len(word) > target_length:
                return word[:target_length]

        # Паттерны по длине
        if target_length == 4:
            if roll < 0.60:
                return self._generate_cvcv()
            return self._generate_vcvc()
        elif target_length == 5:
            if roll < 0.55:
                return self._generate_vcvcv()
            return self._generate_cvvcv()
        elif target_length == 6:
            if roll < 0.60:
                return self._generate_cvcvcv()
            # CVVCV + случайная согласная в конце
            base = self._generate_cvvcv()
            return base + random.choice(self.CONSONANTS)
        elif target_length == 7:
            # CVCVCV + согласная или CVCV + CVC
            if roll < 0.50:
                return self._generate_cvcvcv() + random.choice(self.CONSONANTS)
            return self._generate_cvcv() + self._generate_vcvc()[:3]
        else:
            # Для других длин — фоллбэк на CVCV + остаток
            base = self._generate_cvcv()
            while len(base) < target_length:
                base += random.choice(self.VOWELS if len(base) % 2 == 0 else self.CONSONANTS)
            return base[:target_length]

    def generate_batch(
        self,
        count: int,
        existing: Optional[set[str]] = None,
    ) -> list[str]:
        """Сгенерировать батч уникальных premium-юзернеймов."""
        if existing is None:
            existing = set()

        usernames: set[str] = set()
        attempts = 0
        max_attempts = count * 30

        while len(usernames) < count and attempts < max_attempts:
            target_length = random.randint(self.min_length, self.max_length)
            candidate = self._generate_one(target_length)

            if (
                candidate.isalpha()
                and candidate.islower()
                and self.min_length <= len(candidate) <= self.max_length
                and candidate not in existing
                and candidate not in usernames
                and len(candidate) >= 4  # минимум 4 для premium
            ):
                usernames.add(candidate)

            attempts += 1

        result = list(usernames)
        logger.debug(
            "Premium-батч: %d юзов (попыток: %d)", len(result), attempts
        )
        return result


# ──────────────────────────────────────────────
#  1. UsernameGenerator — читаемые комбинации (random mode)
# ──────────────────────────────────────────────

class UsernameGenerator:
    """
    Генератор читаемых юзернеймов на основе чередования
    гласных и согласных букв латиницы.

    Принцип:
      - Строка начинается с согласной (70% вероятности) или гласной (30%).
      - Каждый следующий символ чередует тип: после гласной → согласная, и наоборот.
      - Это даёт произносимые комбинации: "vibroxi", "klozet", "zenvo".
      - Добавлена опция «двойных гласных» для реалистичности: "teemi", "baako".
    """

    VOWELS: str = "aeiouy"
    CONSONANTS: str = "bcdfghjklmnpqrstvwxz"

    # Популярные суффиксы для разнообразия
    SUFFIXES: list[str] = ["", "", "", "", "x", "o", "i", "a", "s", "z"]

    def __init__(
        self,
        min_length: int = 5,
        max_length: int = 7,
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length

    def _generate_one(self, target_length: int) -> str:
        """
        Сгенерировать один читаемый юзернейм заданной длины.

        Алгоритм чередования:
          1. Выбираем стартовый тип (согласная / гласная).
          2. Чередуем типы, пока не наберём target_length символов.
          3. С вероятностью ~15% вставляем двойную гласную (aa, ee, oo).
        """
        result: list[str] = []

        # Старт: 70% — согласная, 30% — гласная
        use_vowel = random.random() < 0.30

        i = 0
        while len(result) < target_length:
            if use_vowel:
                char = random.choice(self.VOWELS)
                result.append(char)

                # Двойная гласная (15% шанс), если ещё есть место
                if (
                    len(result) < target_length
                    and random.random() < 0.15
                ):
                    result.append(char)
            else:
                char = random.choice(self.CONSONANTS)
                result.append(char)

            use_vowel = not use_vowel
            i += 1

        # Обрезаем до точной длины (на случай двойной гласной)
        username = "".join(result[:target_length])

        # Добавляем случайный суффикс если длина позволяет
        if target_length <= self.max_length and random.random() < 0.20:
            suffix = random.choice(self.SUFFIXES)
            candidate = username + suffix
            if self.min_length <= len(candidate) <= self.max_length:
                username = candidate

        return username[:target_length]  # жёсткая обрезка

    def generate_batch(
        self,
        count: int,
        existing: Optional[set[str]] = None,
    ) -> list[str]:
        """
        Сгенерировать батч уникальных читаемых юзернеймов.

        Args:
            count:   желаемое количество.
            existing: множество уже проверенных юзов (для дедупликации).

        Returns:
            Список уникальных юзернеймов (только a-z, без цифр).
        """
        if existing is None:
            existing = set()

        usernames: set[str] = set()
        attempts = 0
        max_attempts = count * 20  # защита от бесконечного цикла

        while len(usernames) < count and attempts < max_attempts:
            target_length = random.randint(self.min_length, self.max_length)
            candidate = self._generate_one(target_length)

            # Валидация: только a-z, нужная длина, не повтор
            if (
                candidate.isalpha()
                and candidate.islower()
                and self.min_length <= len(candidate) <= self.max_length
                and candidate not in existing
                and candidate not in usernames
            ):
                usernames.add(candidate)

            attempts += 1

        result = list(usernames)
        logger.debug(
            "Сгенерирован батч: %d юзов (попыток: %d)", len(result), attempts
        )
        return result


# ──────────────────────────────────────────────
#  2. TelegramChecker — Pyrogram UserBot
# ──────────────────────────────────────────────

class TelegramChecker:
    """
    Проверка доступности юзернеймов через Pyrogram (MTProto UserBot).

    Использует метод resolve_username. Если выбрасывается
    UsernameNotOccupied — юз свободен.

    Важно: Pyrogram-клиент должен быть запущен (await client.start())
    до вызова любых check-методов.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    async def check_single(self, username: str) -> UsernameStatus:
        """
        Проверить один юзернейм в Telegram.

        Returns:
            FREE     — юзернейм не занят (UsernameNotOccupied)
            TAKEN_TG — юзернейм занят
            INVALID  — некорректный формат
            ERROR    — непредвиденная ошибка
        """
        try:
            await self._client.resolve_username(username)
            # Если не выбросило исключение — юз занят
            return UsernameStatus.TAKEN_TG

        except UsernameNotOccupied:
            return UsernameStatus.FREE

        except UsernameInvalid:
            return UsernameStatus.INVALID

        except FloodWait as fw:
            # FloodWait: ждём указанное сервером время + запас
            wait = fw.value + 1
            logger.warning(
                "FloodWait при проверке @%s: ждём %d сек.", username, wait
            )
            await asyncio.sleep(wait)
            # Повторная попытка после ожидания
            return await self.check_single(username)

        except Exception as exc:
            logger.error("Ошибка TG-проверки @%s: %s", username, exc)
            return UsernameStatus.ERROR

    async def check_batch(
        self,
        usernames: list[str],
        batch_size: int = TG_BATCH_SIZE,
    ) -> dict[str, UsernameStatus]:
        """
        Массовая проверка юзернеймов батчами через asyncio.gather.

        Разбивает список на чанки по batch_size, запускает
        параллельно, между чанками — задержка для защиты от FloodWait.

        Returns:
            Словарь {username: status}
        """
        results: dict[str, UsernameStatus] = {}

        # Разбиваем на чанки
        chunks = [
            usernames[i : i + batch_size]
            for i in range(0, len(usernames), batch_size)
        ]

        for chunk_idx, chunk in enumerate(chunks, start=1):
            logger.info(
                "TG-проверка: чанк %d/%d (%d юзов)",
                chunk_idx, len(chunks), len(chunk),
            )

            tasks = [self.check_single(u) for u in chunk]
            statuses = await asyncio.gather(*tasks, return_exceptions=True)

            for username, status in zip(chunk, statuses):
                if isinstance(status, Exception):
                    logger.error(
                        "Исключение при проверке @%s: %s", username, status
                    )
                    results[username] = UsernameStatus.ERROR
                else:
                    results[username] = status

            # Задержка между чанками (кроме последнего)
            if chunk_idx < len(chunks):
                await asyncio.sleep(TG_BATCH_DELAY)

        free_count = sum(
            1 for s in results.values() if s == UsernameStatus.FREE
        )
        logger.info(
            "TG-проверка завершена: %d свободных из %d",
            free_count, len(usernames),
        )
        return results


# ──────────────────────────────────────────────
#  3. FragmentChecker — проверка на Fragment.com
# ──────────────────────────────────────────────

class FragmentChecker:
    """
    Проверка статуса юзернейма на fragment.com через aiohttp.

    Парсим HTML-ответ страницы https://fragment.com/username/{username}.
    Ищем индикаторы:
      - "Available"  → юз 100% свободен
      - "Auction"    → на аукционе → занят
      - "Taken"      → занят
      - "Unavailable"→ занят

    Используем простейший HTML-парсинг без BeautifulSoup,
    т.к. структура Fragment минимальна и стабильна.
    """

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ленивая инициализация aiohttp-сессии."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    async def check_single(self, username: str) -> UsernameStatus:
        """
        Проверить статус юзернейма на Fragment.

        Returns:
            FREE           — "Available"
            TAKEN_FRAGMENT — "Auction", "Taken", "Unavailable"
            ERROR          — ошибка запроса / парсинга
        """
        url = f"{FRAGMENT_BASE_URL}/{username}"
        session = await self._ensure_session()

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(
                        "Fragment вернул статус %d для @%s",
                        response.status, username,
                    )
                    return UsernameStatus.ERROR

                html = await response.text()

                # Ищем ключевые слова в ответе
                html_lower = html.lower()

                if "available" in html_lower:
                    # Уточняем: ищем более конкретные паттерны
                    # Fragment показывает "Available for purchase" или просто "Available"
                    if "auction" in html_lower:
                        return UsernameStatus.TAKEN_FRAGMENT
                    return UsernameStatus.FREE

                if "auction" in html_lower:
                    return UsernameStatus.TAKEN_FRAGMENT

                if "taken" in html_lower or "unavailable" in html_lower:
                    return UsernameStatus.TAKEN_FRAGMENT

                # Если ни один паттерн не найден — считаем занятым
                logger.debug(
                    "Fragment: неопределённый статус для @%s, считаем занятым",
                    username,
                )
                return UsernameStatus.TAKEN_FRAGMENT

        except asyncio.TimeoutError:
            logger.warning("Fragment timeout для @%s", username)
            return UsernameStatus.ERROR

        except aiohttp.ClientError as exc:
            logger.warning("Fragment client error для @%s: %s", username, exc)
            return UsernameStatus.ERROR

        except Exception as exc:
            logger.error("Fragment unexpected error для @%s: %s", username, exc)
            return UsernameStatus.ERROR

    async def check_batch(
        self,
        usernames: list[str],
        batch_size: int = 10,  # Fragment строже с лимитами
        delay: float = 1.0,
    ) -> dict[str, UsernameStatus]:
        """
        Массовая Fragment-проверка с контролем скорости.

        Fragment более строг к FloodWait, поэтому:
          - batch_size = 10 (меньше, чем для TG)
          - delay = 1.0 сек между запросами
        """
        results: dict[str, UsernameStatus] = {}

        # По одному запросу с задержкой (Fragment не любит параллелизм)
        for i, username in enumerate(usernames):
            results[username] = await self.check_single(username)

            # Задержка между запросами
            if i < len(usernames) - 1:
                await asyncio.sleep(delay)

        free_count = sum(
            1 for s in results.values() if s == UsernameStatus.FREE
        )
        logger.info(
            "Fragment-проверка завершена: %d свободных из %d",
            free_count, len(usernames),
        )
        return results

    async def close(self) -> None:
        """Закрыть aiohttp-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Fragment aiohttp-сессия закрыта.")


# ──────────────────────────────────────────────
#  4. UsernameFinder — оркестратор
# ──────────────────────────────────────────────

class UsernameFinder:
    """
    Главный оркестратор поиска красивых свободных юзернеймов.

    Пайплайн:
      1. Генерация батча читаемых комбинаций
      2. Проверка в Telegram (Pyrogram) — массово через asyncio.gather
      3. Фильтрация: оставляем только FREE в TG
      4. Проверка на Fragment (aiohttp) — последовательно
      5. Фильтрация: оставляем только FREE на Fragment
      6. Дедупликация через БД
      7. Возврат списка UsernameResult со статусом FREE
    """

    def __init__(
        self,
        pyrogram_client: Client,
        db: Database,
        min_length: int = 5,
        max_length: int = 7,
        batch_size: int = TG_BATCH_SIZE,
        gen_mode: str = "random",
    ) -> None:
        self._db = db
        self._gen_mode = gen_mode
        self._generator = UsernameGenerator(min_length, max_length)
        self._premium_generator = PremiumGenerator(min_length, max_length)
        self._tg_checker = TelegramChecker(pyrogram_client)
        self._fragment_checker = FragmentChecker()
        self._batch_size = batch_size

        # Множество уже найденных юзов (для in-memory дедупа при генерации)
        self._seen_usernames: set[str] = set()

        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def search_cycle(
        self,
        count: int = 200,
    ) -> list[UsernameResult]:
        """
        Один цикл поиска: генерация → TG → Fragment → дедуп.

        Args:
            count: сколько юзернеймов сгенерировать за цикл.

        Returns:
            Список 100% свободных юзернеймов (UsernameStatus.FREE).
        """
        self._running = True
        free_results: list[UsernameResult] = []

        try:
            # ── Шаг 1: Генерация (выбор генератора по gen_mode) ──
            gen = (
                self._premium_generator
                if self._gen_mode == "premium"
                else self._generator
            )
            logger.info(
                "Генерация батча: %d юзов (режим: %s)...", count, self._gen_mode
            )
            usernames = gen.generate_batch(
                count=count,
                existing=self._seen_usernames,
            )

            if not usernames:
                logger.warning("Не удалось сгенерировать ни одного нового юза.")
                return free_results

            logger.info("Сгенерировано %d уникальных юзов.", len(usernames))

            # ── Шаг 2: Проверка в Telegram ──
            logger.info("Проверка в Telegram...")
            tg_results = await self._tg_checker.check_batch(
                usernames, batch_size=self._batch_size
            )

            # Фильтруем: оставляем только FREE
            free_in_tg = [
                u for u, s in tg_results.items()
                if s == UsernameStatus.FREE
            ]
            logger.info("Свободны в TG: %d из %d", len(free_in_tg), len(usernames))

            if not free_in_tg:
                return free_results

            # ── Шаг 3: Проверка на Fragment ──
            logger.info("Проверка на Fragment (%d кандидатов)...", len(free_in_tg))
            fragment_results = await self._fragment_checker.check_batch(free_in_tg)

            # ── Шаг 4: Финальная фильтрация + дедупликация ──
            for username, frag_status in fragment_results.items():
                if frag_status != UsernameStatus.FREE:
                    continue

                # Дедупликация через БД
                if await self._db.username_already_found(username):
                    logger.debug("@%s уже был найден ранее — пропускаем.", username)
                    continue

                # 100% свободный!
                result = UsernameResult(
                    username=username,
                    length=len(username),
                    status=UsernameStatus.FREE,
                )
                free_results.append(result)

                # Записываем в БД и in-memory set
                await self._db.mark_username_found(username, len(username))
                self._seen_usernames.add(username)

                logger.info(
                    "🎉 Найден свободный юз: @%s (длина: %d)",
                    username, len(username),
                )

        except Exception as exc:
            logger.error("Ошибка в цикле поиска юзов: %s", exc)

        finally:
            self._running = False

        logger.info(
            "Цикл завершён. Найдено %d свободных юзов.", len(free_results)
        )
        return free_results

    async def load_seen_from_db(self) -> None:
        """Загрузить ранее найденные юзы из БД в in-memory set."""
        try:
            # Простой подход: читаем все найденные юзы
            rows = await self._db._fetchall(
                "SELECT username FROM found_usernames"
            )
            self._seen_usernames = {row["username"] for row in rows}
            logger.info(
                "Загружено %d ранее найденных юзов из БД.",
                len(self._seen_usernames),
            )
        except Exception as exc:
            logger.error("Ошибка загрузки seen_usernames: %s", exc)
            self._seen_usernames = set()

    async def close(self) -> None:
        """Закрыть ресурсы."""
        await self._fragment_checker.close()
        logger.info("UsernameFinder закрыт.")


# ──────────────────────────────────────────────
#  5. Pyrogram Client Factory — AUTH_KEY_HEX
# ──────────────────────────────────────────────

def _create_session_from_auth_key(
    session_name: str,
    auth_key_hex: str,
    dc_id: int,
) -> None:
    """
    Создать Pyrogram-совместимый .session файл из AUTH_KEY_HEX + DC_ID.

    Pyrogram использует SQLite-файл <name>.session с таблицей sessions,
    где хранится auth_key (256 байт = 512 hex символов) и dc_id.

    Формат сессии Pyrogram (таблица sessions):
        dc_id   INTEGER
        api_id  INTEGER  (0 — не используется при готовом auth_key)
        auth_key BLOB    (256 байт)

    Args:
        session_name:  имя сессии (без расширения .session).
        auth_key_hex:  512 hex-символов (256 байт авторизационного ключа).
        dc_id:         номер DC (1-5). Обычно 2 для Европы.
    """
    session_path = f"{session_name}.session"

    import sqlite3

    auth_key_bytes = bytes.fromhex(auth_key_hex)
    if len(auth_key_bytes) != 256:
        raise ValueError(
            f"AUTH_KEY_HEX должен быть 512 hex-символов (256 байт), "
            f"получено {len(auth_key_hex)} символов."
        )

    conn = sqlite3.connect(session_path)
    cursor = conn.cursor()

    # Создаём таблицу сессий (формат Pyrogram)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            dc_id     INTEGER PRIMARY KEY,
            api_id    INTEGER NOT NULL,
            api_hash  TEXT    NOT NULL,
            auth_key  BLOB    NOT NULL,
            date      INTEGER NOT NULL DEFAULT 0,
            test_mode INTEGER NOT NULL DEFAULT 0,
            name      TEXT    NOT NULL DEFAULT ''
        )
    """)

    # Проверяем, есть ли уже запись для этого DC
    cursor.execute("SELECT 1 FROM sessions WHERE dc_id = ?", (dc_id,))
    exists = cursor.fetchone()

    if exists:
        cursor.execute(
            "UPDATE sessions SET auth_key = ? WHERE dc_id = ?",
            (auth_key_bytes, dc_id),
        )
    else:
        # api_id/api_hash — не используются, но Pyrogram требует их в таблице
        cursor.execute(
            """
            INSERT INTO sessions (dc_id, api_id, api_hash, auth_key)
            VALUES (?, 0, '', ?)
            """,
            (dc_id, auth_key_bytes),
        )

    conn.commit()
    conn.close()
    logger.info(
        "Session-файл создан: %s (dc_id=%d, auth_key=%d байт)",
        session_path, dc_id, len(auth_key_bytes),
    )


def create_pyrogram_client() -> Client:
    """
    Создать Pyrogram UserBot-клиент на основе AUTH_KEY_HEX + DC_ID.

    В отличие от стандартного подхода (API_ID + API_HASH + интерактивный вход),
    этот метод использует готовый авторизационный ключ, извлечённый
    из существующей сессии Pyrogram или Telethon.

    Как получить AUTH_KEY_HEX:
      1. Из Pyrogram-сессии:
         import sqlite3; conn = sqlite3.connect("userbot_session.session")
         row = conn.execute("SELECT auth_key, dc_id FROM sessions").fetchone()
         auth_key_hex = row[0].hex(); dc_id = row[1]
      2. Из Telethon-сессии: аналогично, таблица sessions.

    Важно: клиент НЕ запускается здесь. Запуск делается в main.py:
        client = create_pyrogram_client()
        await client.start()
    """
    if not AUTH_KEY_HEX:
        raise ValueError(
            "AUTH_KEY_HEX не задан! Установите переменную окружения AUTH_KEY_HEX "
            "(512 hex-символов авторизационного ключа)."
        )

    # Создаём/обновляем .session файл из AUTH_KEY
    _create_session_from_auth_key(
        session_name=PYROGRAM_SESSION,
        auth_key_hex=AUTH_KEY_HEX,
        dc_id=DC_ID,
    )

    # Pyrogram-клиент: api_id/api_hash минимальные (не используются для auth)
    # При наличии готового .session файла Pyrogram подключится
    # к указанному DC с готовым auth_key без запроса номера/кода.
    client = Client(
        name=PYROGRAM_SESSION,
        api_id=2040,          # dummy — не используется при готовой сессии
        api_hash="b18441a1ff607e10a9898944b709746",  # dummy
        # no_proxy — локальный запуск без прокси
    )
    logger.info(
        "Pyrogram-клиент создан (session: %s, DC%d, auth_key из HEX).",
        PYROGRAM_SESSION, DC_ID,
    )
    return client
