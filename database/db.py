"""
database/db.py — Асинхронная работа с aiosqlite.

Единственный экземпляр Database управляет соединением,
создаёт таблицы при первом запуске и предоставляет
type-hinted методы для всех CRUD-операций бота.

Таблицы:
    users         — текущий режим пользователя (avito / tg)
    filters       — фильтры Авито (keyword, category, min/max цена)
    sent_ads      — дедупликация отправленных объявлений
    parser_state  — состояние парсера Авито (last_parse_time, is_running)
    tg_settings   — настройки поиска юзов (длина, is_running)
    found_usernames — найденные свободные юзернеймы (дедупликация)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """Асинхронная обёртка над aiosqlite с автоматическим созданием таблиц."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path: str = str(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    # ──────────────────────────────────────────
    #  Connection lifecycle
    # ──────────────────────────────────────────

    async def connect(self) -> None:
        """Открыть соединение и включить WAL-режим для лучшей производительности."""
        try:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            logger.info("БД подключена: %s", self._db_path)
        except Exception as exc:
            logger.critical("Не удалось подключиться к БД %s: %s", self._db_path, exc)
            raise

    async def disconnect(self) -> None:
        """Закрыть соединение безопасно."""
        if self._conn is not None:
            try:
                await self._conn.close()
                logger.info("Соединение с БД закрыто.")
            except Exception as exc:
                logger.warning("Ошибка при закрытии БД: %s", exc)
            finally:
                self._conn = None

    async def _execute(
        self,
        query: str,
        params: tuple = (),
    ) -> aiosqlite.Cursor:
        """Внутренний метод: выполнить запрос с логированием ошибок."""
        if self._conn is None:
            raise RuntimeError("БД не подключена. Вызовите await db.connect() первым.")
        try:
            cursor = await self._conn.execute(query, params)
            await self._conn.commit()
            return cursor
        except Exception as exc:
            logger.error("SQL ошибка: %s | query: %s | params: %s", exc, query, params)
            raise

    async def _fetchall(
        self,
        query: str,
        params: tuple = (),
    ) -> list[aiosqlite.Row]:
        """Внутренний метод: fetchall с логированием."""
        if self._conn is None:
            raise RuntimeError("БД не подключена.")
        try:
            cursor = await self._conn.execute(query, params)
            return await cursor.fetchall()
        except Exception as exc:
            logger.error("SQL fetchall ошибка: %s | query: %s", exc, query)
            raise

    async def _fetchone(
        self,
        query: str,
        params: tuple = (),
    ) -> Optional[aiosqlite.Row]:
        """Внутренний метод: fetchone с логированием."""
        if self._conn is None:
            raise RuntimeError("БД не подключена.")
        try:
            cursor = await self._conn.execute(query, params)
            return await cursor.fetchone()
        except Exception as exc:
            logger.error("SQL fetchone ошибка: %s | query: %s", exc, query)
            raise

    # ──────────────────────────────────────────
    #  Table creation (миграции)
    # ──────────────────────────────────────────

    async def create_tables(self) -> None:
        """
        Создать все таблицы, если они не существуют.
        Затем запустить миграции (ALTER TABLE для новых колонок).
        Вызывать один раз при старте бота.
        """
        if self._conn is None:
            raise RuntimeError("БД не подключена.")

        try:
            await self._conn.executescript(SCHEMA_SQL)
            await self._conn.commit()
            logger.info("Все таблицы созданы / подтверждены.")
        except Exception as exc:
            logger.critical("Ошибка создания таблиц: %s", exc)
            raise

        # Миграции (безопасные ALTER TABLE — IF NOT EXISTS через pragma)
        await self._run_migrations()

    async def _run_migrations(self) -> None:
        """
        Применить миграции к существующей БД.
        Каждая миграция — ALTER TABLE ADD COLUMN, защищённый
        проверкой pragma_table_info (чтобы не упасть при повторе).
        """
        if self._conn is None:
            return

        migrations = [
            # ── Migration 001: gen_mode в tg_settings ──
            (
                "ALTER TABLE tg_settings ADD COLUMN gen_mode TEXT "
                "NOT NULL DEFAULT 'random' "
                "CHECK (gen_mode IN ('random', 'premium'))",
                "tg_settings",
                "gen_mode",
            ),
        ]

        for sql, table, column in migrations:
            try:
                # Проверяем, есть ли уже колонка
                cursor = await self._conn.execute(
                    f"PRAGMA table_info({table})"
                )
                columns = await cursor.fetchall()
                col_names = {row[1] for row in columns}

                if column not in col_names:
                    await self._conn.execute(sql)
                    await self._conn.commit()
                    logger.info("Миграция применена: %s.%s", table, column)
                else:
                    logger.debug("Колонка %s.%s уже существует — пропуск.", table, column)
            except Exception as exc:
                logger.error("Ошибка миграции %s.%s: %s", table, column, exc)

    # ──────────────────────────────────────────
    #  users — режим пользователя
    # ──────────────────────────────────────────

    async def get_user_mode(self, user_id: int) -> Optional[str]:
        """Вернуть текущий режим пользователя ('avito' / 'tg') или None."""
        row = await self._fetchone(
            "SELECT current_mode FROM users WHERE user_id = ?",
            (user_id,),
        )
        return row["current_mode"] if row else None

    async def set_user_mode(self, user_id: int, mode: str) -> None:
        """Установить режим пользователя. upsert."""
        await self._execute(
            """
            INSERT INTO users (user_id, current_mode)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET current_mode = excluded.current_mode;
            """,
            (user_id, mode),
        )
        logger.info("Пользователь %d → режим: %s", user_id, mode)

    async def ensure_user(self, user_id: int) -> None:
        """Создать запись пользователя, если её ещё нет."""
        await self._execute(
            """
            INSERT OR IGNORE INTO users (user_id, current_mode)
            VALUES (?, 'avito');
            """,
            (user_id,),
        )

    # ──────────────────────────────────────────
    #  filters — фильтры Авито
    # ──────────────────────────────────────────

    async def get_filters(self, user_id: int) -> Optional[aiosqlite.Row]:
        """Получить текущие фильтры Авито для пользователя."""
        return await self._fetchone(
            "SELECT * FROM filters WHERE user_id = ?",
            (user_id,),
        )

    async def set_filters(
        self,
        user_id: int,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
    ) -> None:
        """Установить/обновить фильтры Авито. upsert."""
        await self._execute(
            """
            INSERT INTO filters (user_id, keyword, category, min_price, max_price)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                keyword    = COALESCE(excluded.keyword,    filters.keyword),
                category   = COALESCE(excluded.category,   filters.category),
                min_price  = COALESCE(excluded.min_price,  filters.min_price),
                max_price  = COALESCE(excluded.max_price,  filters.max_price);
            """,
            (user_id, keyword, category, min_price, max_price),
        )
        logger.info("Фильтры обновлены для user_id=%d", user_id)

    async def clear_filters(self, user_id: int) -> None:
        """Сбросить фильтры Авито для пользователя."""
        await self._execute(
            "DELETE FROM filters WHERE user_id = ?",
            (user_id,),
        )
        logger.info("Фильтры сброшены для user_id=%d", user_id)

    # ──────────────────────────────────────────
    #  sent_ads — дедупликация объявлений Авито
    # ──────────────────────────────────────────

    async def ad_already_sent(self, user_id: int, ad_id: str) -> bool:
        """Проверить, отправляли ли мы это объявление ранее."""
        row = await self._fetchone(
            "SELECT 1 FROM sent_ads WHERE user_id = ? AND ad_id = ?",
            (user_id, ad_id),
        )
        return row is not None

    async def mark_ad_sent(self, user_id: int, ad_id: str) -> None:
        """Записать, что объявление отправлено."""
        await self._execute(
            """
            INSERT OR IGNORE INTO sent_ads (user_id, ad_id, sent_time)
            VALUES (?, ?, ?);
            """,
            (user_id, ad_id, datetime.utcnow().isoformat()),
        )

    async def get_sent_ads_count(self, user_id: int) -> int:
        """Количество отправленных объявлений для пользователя."""
        row = await self._fetchone(
            "SELECT COUNT(*) AS cnt FROM sent_ads WHERE user_id = ?",
            (user_id,),
        )
        return row["cnt"] if row else 0

    # ──────────────────────────────────────────
    #  parser_state — состояние парсера Авито
    # ──────────────────────────────────────────

    async def get_parser_state(self) -> Optional[aiosqlite.Row]:
        """Получить текущее состояние парсера (singleton row id=1)."""
        return await self._fetchone("SELECT * FROM parser_state WHERE id = 1")

    async def set_parser_running(self, is_running: bool) -> None:
        """Установить флаг is_running."""
        await self._execute(
            """
            INSERT INTO parser_state (id, is_running, last_parse_time)
            VALUES (1, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET is_running = excluded.is_running;
            """,
            (is_running,),
        )
        logger.info("Парсер Авито is_running=%s", is_running)

    async def update_last_parse_time(self, parse_time: datetime) -> None:
        """Обновить время последнего парса."""
        await self._execute(
            """
            UPDATE parser_state SET last_parse_time = ? WHERE id = 1;
            """,
            (parse_time.isoformat(),),
        )

    async def get_last_parse_time(self) -> Optional[datetime]:
        """Вернуть last_parse_time как datetime или None."""
        row = await self._fetchone(
            "SELECT last_parse_time FROM parser_state WHERE id = 1"
        )
        if row and row["last_parse_time"]:
            return datetime.fromisoformat(row["last_parse_time"])
        return None

    async def is_parser_running(self) -> bool:
        """Быстрая проверка: запущен ли парсер."""
        row = await self._fetchone(
            "SELECT is_running FROM parser_state WHERE id = 1"
        )
        return bool(row["is_running"]) if row else False

    # ──────────────────────────────────────────
    #  tg_settings — настройки поиска юзернеймов
    # ──────────────────────────────────────────

    async def get_tg_settings(self, user_id: int) -> Optional[aiosqlite.Row]:
        """Получить настройки TG-поиска для пользователя."""
        return await self._fetchone(
            "SELECT * FROM tg_settings WHERE user_id = ?",
            (user_id,),
        )

    async def set_tg_settings(
        self,
        user_id: int,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        is_running: Optional[bool] = None,
        gen_mode: Optional[str] = None,
    ) -> None:
        """Установить/обновить настройки TG-поиска. upsert."""
        await self._execute(
            """
            INSERT INTO tg_settings (user_id, min_length, max_length, is_running, gen_mode)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                min_length  = COALESCE(excluded.min_length,  tg_settings.min_length),
                max_length  = COALESCE(excluded.max_length,  tg_settings.max_length),
                is_running  = COALESCE(excluded.is_running,  tg_settings.is_running),
                gen_mode    = COALESCE(excluded.gen_mode,    tg_settings.gen_mode);
            """,
            (user_id, min_length, max_length, is_running, gen_mode),
        )
        logger.info("TG-настройки обновлены для user_id=%d", user_id)

    async def set_tg_running(self, user_id: int, is_running: bool) -> None:
        """Быстро переключить флаг is_running."""
        await self.set_tg_settings(user_id, is_running=is_running)

    async def is_tg_running(self, user_id: int) -> bool:
        """Быстрая проверка: запущен ли TG-поиск."""
        row = await self._fetchone(
            "SELECT is_running FROM tg_settings WHERE user_id = ?",
            (user_id,),
        )
        return bool(row["is_running"]) if row else False

    # ──────────────────────────────────────────
    #  found_usernames — дедупликация найденных юзов
    # ──────────────────────────────────────────

    async def username_already_found(self, username: str) -> bool:
        """Проверить, находили ли мы этот юз ранее."""
        row = await self._fetchone(
            "SELECT 1 FROM found_usernames WHERE username = ?",
            (username,),
        )
        return row is not None

    async def mark_username_found(self, username: str, length: int) -> None:
        """Записать найденный свободный юзернейм."""
        await self._execute(
            """
            INSERT OR IGNORE INTO found_usernames (username, length, found_time)
            VALUES (?, ?, ?);
            """,
            (username, length, datetime.utcnow().isoformat()),
        )

    async def get_found_usernames_count(self) -> int:
        """Сколько всего уникальных юзов найдено."""
        row = await self._fetchone("SELECT COUNT(*) AS cnt FROM found_usernames")
        return row["cnt"] if row else 0


# ──────────────────────────────────────────────
#  SQL Schema — единый DDL-скрипт
# ──────────────────────────────────────────────

SCHEMA_SQL: str = """
-- =============================================
-- users: режим пользователя (avito / tg)
-- =============================================
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    current_mode TEXT    NOT NULL DEFAULT 'avito'
        CHECK (current_mode IN ('avito', 'tg'))
);

-- =============================================
-- filters: фильтры парсера Авито
-- =============================================
CREATE TABLE IF NOT EXISTS filters (
    user_id   INTEGER PRIMARY KEY
        REFERENCES users(user_id) ON DELETE CASCADE,
    keyword   TEXT,
    category  TEXT,
    min_price INTEGER,
    max_price INTEGER
);

-- =============================================
-- sent_ads: дедупликация отправленных объявлений
-- =============================================
CREATE TABLE IF NOT EXISTS sent_ads (
    user_id   INTEGER NOT NULL
        REFERENCES users(user_id) ON DELETE CASCADE,
    ad_id     TEXT    NOT NULL,
    sent_time TEXT    NOT NULL,
    PRIMARY KEY (user_id, ad_id)
);

-- =============================================
-- parser_state: глобальное состояние парсера Авито
-- (singleton — единственная строка с id = 1)
-- =============================================
CREATE TABLE IF NOT EXISTS parser_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    is_running      INTEGER NOT NULL DEFAULT 0
        CHECK (is_running IN (0, 1)),
    last_parse_time TEXT
);

-- =============================================
-- tg_settings: настройки поиска юзернеймов
-- =============================================
CREATE TABLE IF NOT EXISTS tg_settings (
    user_id    INTEGER PRIMARY KEY
        REFERENCES users(user_id) ON DELETE CASCADE,
    min_length INTEGER NOT NULL DEFAULT 5
        CHECK (min_length BETWEEN 3 AND 32),
    max_length INTEGER NOT NULL DEFAULT 7
        CHECK (max_length BETWEEN 3 AND 32),
    is_running INTEGER NOT NULL DEFAULT 0
        CHECK (is_running IN (0, 1)),
    gen_mode   TEXT    NOT NULL DEFAULT 'random'
        CHECK (gen_mode IN ('random', 'premium'))
);

-- =============================================
-- found_usernames: дедупликация найденных юзов
-- =============================================
CREATE TABLE IF NOT EXISTS found_usernames (
    username   TEXT    PRIMARY KEY,
    length     INTEGER NOT NULL
        CHECK (length BETWEEN 3 AND 32),
    found_time TEXT    NOT NULL
);

-- =============================================
-- Индексы для производительности
-- =============================================
CREATE INDEX IF NOT EXISTS idx_sent_ads_user
    ON sent_ads(user_id);

CREATE INDEX IF NOT EXISTS idx_sent_ads_ad
    ON sent_ads(ad_id);

CREATE INDEX IF NOT EXISTS idx_found_usernames_length
    ON found_usernames(length);

CREATE INDEX IF NOT EXISTS idx_found_usernames_time
    ON found_usernames(found_time);
"""
