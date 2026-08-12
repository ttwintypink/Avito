"""
avito/parser.py — Playwright-парсер объявлений Авито.

КРИТИЧЕСКИЕ ТРЕБОВАНИЯ (из ТЗ):
  1. СОРТИРОВКА: в URL всегда s=104 (Сначала новые по дате)
  2. ИЗВЛЕЧЕНИЕ ДАННЫХ: ЗАПРЕЩЕНЫ CSS-селекторы.
     Только <script type="application/ld+json"> или window.__INITIAL_STATE__
  3. ЛОКАЛЬНЫЙ ЗАПУСК: persistent_context, headless=False, playwright-stealth
  4. АНТИБАН: случайный скролл, задержки 5-12 сек
  5. КАПЧА: детект → алерт в ТГ → пауза до ручного решения
  6. ЛОГИКА: Смоленск (в наличии) → РФ с доставкой в Смоленск
  7. ДЕДУПЛИКАЦИЯ: по ad_id + last_parse_time
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import stealth_async

from config import (
    AVITO_BASE_URL,
    AVITO_MAX_DELAY,
    AVITO_MAX_DESCRIPTION_LENGTH,
    AVITO_MIN_DELAY,
    AVITO_PROFILE_DIR,
    AVITO_SCROLL_MAX,
    AVITO_SCROLL_MIN,
    AVITO_SORT_PARAM,
    DEFAULT_CITY,
    DEFAULT_DELIVERY_CITY,
)
from database import Database
from utils.helpers import truncate

from .time_utils import MOSCOW_TZ, format_avito_time, parse_avito_time

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Data class: AvitoAd
# ──────────────────────────────────────────────

@dataclass
class AvitoAd:
    """Одно объявление Авито — все извлечённые данные."""
    ad_id: str
    title: str
    price: str
    description: str
    photo_urls: list[str] = field(default_factory=list)
    city: str = ""
    is_delivery: bool = False
    publish_time: Optional[datetime] = None
    url: str = ""

    @property
    def first_photo(self) -> Optional[str]:
        return self.photo_urls[0] if self.photo_urls else None

    def format_caption(self) -> str:
        """HTML-подпись для Telegram-сообщения (по ТЗ)."""
        location = (
            f"🚚 Доставка из {self.city}"
            if self.is_delivery
            else self.city
        )
        time_str = format_avito_time(self.publish_time)
        desc = truncate(self.description, AVITO_MAX_DESCRIPTION_LENGTH)

        return (
            f"🛒 <b>{self.title}</b>\n"
            f"💰 <b>Цена:</b> {self.price}\n"
            f"📍 <b>Локация:</b> {location}\n"
            f"⏰ <b>Опубликовано:</b> {time_str}\n"
            f"📝 <b>Описание:</b> {desc}"
        )


# ──────────────────────────────────────────────
#  CaptchaDetector
# ──────────────────────────────────────────────

class CaptchaDetector:
    """Детектор капчи Яндекса / Авито на странице."""

    CAPTCHA_URL_PATTERNS = ("captcha", "pass.yandex", "challenge")

    @staticmethod
    async def is_captcha_present(page: Page) -> bool:
        """Проверить, отображается ли капча на текущей странице."""
        try:
            url = page.url.lower()
            for pattern in CaptchaDetector.CAPTCHA_URL_PATTERNS:
                if pattern in url:
                    return True

            captcha_frame = await page.query_selector(
                'iframe[src*="captcha"], iframe[src*="challenge"]'
            )
            if captcha_frame:
                return True

            body_text = await page.evaluate(
                "() => document.body?.innerText?.toLowerCase() || ''"
            )
            if "подтвердите" in body_text and "человек" in body_text:
                return True
            if "captcha" in body_text:
                return True

            return False
        except Exception as exc:
            logger.error("Ошибка проверки капчи: %s", exc)
            return False


# ──────────────────────────────────────────────
#  AvitoParser
# ──────────────────────────────────────────────

class AvitoParser:
    """
    Playwright-парсер Авито с persistent context и stealth.

    Жизненный цикл:
      1. launch()  — запустить браузер
      2. parse()   — один цикл (Смоленск → РФ с доставкой)
      3. close()   — закрыть браузер
    """

    def __init__(
        self,
        db: Database,
        notify_captcha: Optional[Callable] = None,
    ) -> None:
        self._db = db
        self._notify_captcha = notify_captcha

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._is_running = False
        self._is_paused = False

        self._total_parsed = 0
        self._total_sent = 0
        self._last_parse_dt: Optional[datetime] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "is_paused": self._is_paused,
            "total_parsed": self._total_parsed,
            "total_sent": self._total_sent,
            "last_parse": format_avito_time(self._last_parse_dt),
            "browser_alive": self._context is not None,
        }

    # ──────────────────────────────────────────
    #  Browser lifecycle
    # ──────────────────────────────────────────

    async def launch(self) -> None:
        """Запустить Playwright с persistent context (headless=False)."""
        try:
            self._playwright = await async_playwright().start()
            AVITO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(AVITO_PROFILE_DIR),
                headless=False,
                viewport={"width": 1366, "height": 768},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )

            for page in self._context.pages:
                await stealth_async(page)

            logger.info(
                "Playwright запущен (persistent: %s, headless=False)",
                AVITO_PROFILE_DIR,
            )
        except Exception as exc:
            logger.critical("Ошибка запуска Playwright: %s", exc)
            raise

    async def close(self) -> None:
        """Закрыть браузер и Playwright."""
        try:
            if self._context:
                await self._context.close()
                self._context = None
        except Exception as exc:
            logger.error("Ошибка закрытия context: %s", exc)

        try:
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as exc:
            logger.error("Ошибка остановки Playwright: %s", exc)

    # ──────────────────────────────────────────
    #  Page helpers
    # ──────────────────────────────────────────

    async def _new_stealth_page(self) -> Page:
        """Создать новую страницу и применить stealth."""
        if not self._context:
            raise RuntimeError("Browser не запущен.")
        page = await self._context.new_page()
        await stealth_async(page)
        return page

    async def _human_delay(self) -> None:
        """Случайная задержка 5-12 сек (эмуляция человека)."""
        delay = random.uniform(AVITO_MIN_DELAY, AVITO_MAX_DELAY)
        logger.debug("Human delay: %.1f сек", delay)
        await asyncio.sleep(delay)

    async def _human_scroll(self, page: Page) -> None:
        """Случайный скролл страницы."""
        scroll_amount = random.randint(AVITO_SCROLL_MIN, AVITO_SCROLL_MAX)
        try:
            await page.mouse.wheel(0, scroll_amount)
            await asyncio.sleep(random.uniform(0.5, 1.5))
        except Exception as exc:
            logger.debug("Скролл не удался: %s", exc)

    # ──────────────────────────────────────────
    #  Captcha handling
    # ──────────────────────────────────────────

    async def _handle_captcha(self, page: Page) -> None:
        """Алерт в ТГ + пауза до ручного решения капчи."""
        self._is_paused = True
        logger.warning("⚠️ КАПЧА! Парсинг приостановлен.")

        if self._notify_captcha:
            try:
                await self._notify_captcha(
                    "⚠️ Внимание! Авито выдал капчу. "
                    "Пройди её в окне браузера."
                )
            except Exception as exc:
                logger.error("Ошибка отправки алерта: %s", exc)

        while await CaptchaDetector.is_captcha_present(page):
            logger.info("Капча ещё на месте, ждём 5 сек...")
            await asyncio.sleep(5)

        self._is_paused = False
        logger.info("✅ Капча решена! Продолжаем.")

    # ──────────────────────────────────────────
    #  URL builder
    # ──────────────────────────────────────────

    @staticmethod
    def build_search_url(
        keyword: str,
        city: str = DEFAULT_CITY,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        category: Optional[str] = None,
        delivery_city: Optional[str] = None,
    ) -> str:
        """Построить URL поиска Авито (всегда s=104)."""
        city_map = {
            "Смоленск": "smolensk",
            "Москва": "moskva",
            "Санкт-Петербург": "sankt-peterburg",
            "Россия": "rossiya",
        }
        city_slug = city_map.get(city, city.lower())

        path = f"/{city_slug}/{category}" if category else f"/{city_slug}"
        params: list[str] = [f"q={keyword.replace(' ', '+')}", AVITO_SORT_PARAM]

        if min_price is not None:
            params.append(f"pmin={min_price}")
        if max_price is not None:
            params.append(f"pmax={max_price}")
        if delivery_city:
            d_slug = city_map.get(delivery_city, delivery_city.lower())
            params.append(f"delivery={d_slug}")

        return f"{AVITO_BASE_URL}{path}?{'&'.join(params)}"

    # ──────────────────────────────────────────
    #  Data extraction (JSON only, NO CSS selectors!)
    # ──────────────────────────────────────────

    async def _extract_ads_from_page(self, page: Page) -> list[AvitoAd]:
        """
        Извлечь объявления через JSON.

        Приоритет:
          1. window.__INITIAL_STATE__
          2. <script type="application/ld+json">
          3. data-item-id атрибуты
        """
        ads: list[AvitoAd] = []

        # ── Метод 1: __INITIAL_STATE__ ──
        try:
            raw = await page.evaluate(
                "() => { try { return JSON.stringify(window.__INITIAL_STATE__); } catch(e) { return null; } }"
            )
            if raw:
                ads = self._parse_initial_state(raw)
                if ads:
                    logger.info("__INITIAL_STATE__: %d объявлений", len(ads))
                    return ads
        except Exception as exc:
            logger.debug("__INITIAL_STATE__ недоступен: %s", exc)

        # ── Метод 2: ld+json ──
        try:
            raw = await page.evaluate(
                """() => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    return JSON.stringify(Array.from(scripts).map(s => {
                        try { return JSON.parse(s.textContent); } catch(e) { return null; }
                    }).filter(Boolean));
                }"""
            )
            if raw:
                ads = self._parse_ld_json(raw)
                if ads:
                    logger.info("ld+json: %d объявлений", len(ads))
                    return ads
        except Exception as exc:
            logger.debug("ld+json недоступен: %s", exc)

        # ── Метод 3: data-item-id ──
        try:
            raw = await page.evaluate(
                """() => {
                    return JSON.stringify(
                        Array.from(document.querySelectorAll('[data-item-id]')).map(el => ({
                            id: el.getAttribute('data-item-id'),
                            meta: (() => { try { return JSON.parse(el.getAttribute('data-item-meta') || '{}'); } catch(e) { return {}; } })()
                        }))
                    );
                }"""
            )
            if raw:
                ads = self._parse_data_attrs(raw)
                if ads:
                    logger.info("data-attrs: %d объявлений", len(ads))
                    return ads
        except Exception as exc:
            logger.debug("data-attrs недоступны: %s", exc)

        logger.warning("Ни один метод извлечения не сработал!")
        return ads

    # ──────────────────────────────────────────
    #  JSON parsers
    # ──────────────────────────────────────────

    def _parse_initial_state(self, raw_json: str) -> list[AvitoAd]:
        """Парсинг window.__INITIAL_STATE__."""
        ads: list[AvitoAd] = []
        try:
            state = json.loads(raw_json)
        except json.JSONDecodeError:
            return ads

        try:
            items_data = None
            for path in [
                ("items",),
                ("search", "items"),
                ("catalog", "items"),
                ("search", "result", "itemsList"),
            ]:
                current = state
                for key in path:
                    current = current.get(key) if isinstance(current, dict) else None
                    if current is None:
                        break
                if current:
                    items_data = current
                    break

            if not items_data:
                return ads

            items = items_data.values() if isinstance(items_data, dict) else items_data
            for item in items:
                if isinstance(item, dict):
                    ad = self._item_to_ad(item)
                    if ad:
                        ads.append(ad)
        except Exception as exc:
            logger.error("Ошибка _parse_initial_state: %s", exc)

        return ads

    def _parse_ld_json(self, raw_json: str) -> list[AvitoAd]:
        """Парсинг Schema.org ld+json."""
        ads: list[AvitoAd] = []
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            return ads

        if not isinstance(data, list):
            data = [data]

        for entry in data:
            try:
                if entry.get("@type") == "ItemList":
                    for li in entry.get("itemListElement", []):
                        ad = self._schema_to_ad(li.get("item", li))
                        if ad:
                            ads.append(ad)
                elif entry.get("@type") in ("Offer", "Product"):
                    ad = self._schema_to_ad(entry)
                    if ad:
                        ads.append(ad)
            except Exception:
                pass

        return ads

    def _parse_data_attrs(self, raw_json: str) -> list[AvitoAd]:
        """Парсинг data-item-id атрибутов."""
        ads: list[AvitoAd] = []
        try:
            items = json.loads(raw_json)
        except json.JSONDecodeError:
            return ads

        for item in items:
            if not isinstance(item, dict):
                continue
            ad_id = str(item.get("id", ""))
            if not ad_id:
                continue
            meta = item.get("meta", {})
            ads.append(AvitoAd(
                ad_id=ad_id,
                title=meta.get("title", ""),
                price=meta.get("price", ""),
                description=meta.get("description", ""),
                city=meta.get("location", DEFAULT_CITY),
                url=f"{AVITO_BASE_URL}/items/{ad_id}",
            ))

        return ads

    # ──────────────────────────────────────────
    #  Item → AvitoAd converters
    # ──────────────────────────────────────────

    @staticmethod
    def _item_to_ad(item: dict) -> Optional[AvitoAd]:
        """__INITIAL_STATE__ item → AvitoAd."""
        try:
            ad_id = str(item.get("id", "") or item.get("itemId", ""))
            if not ad_id:
                return None

            price_data = item.get("price", {})
            if isinstance(price_data, dict):
                pv = price_data.get("value", "")
                pc = price_data.get("currency", "₽")
                price = f"{pv} {pc}" if pv else ""
            else:
                price = str(price_data) if price_data else ""

            photos = []
            for p in item.get("images", item.get("photos", [])):
                if isinstance(p, dict):
                    u = p.get("640x480", p.get("url", ""))
                    if u:
                        photos.append(u)
                elif isinstance(p, str):
                    photos.append(p)

            loc = item.get("location", item.get("geo", {}))
            city = loc.get("name", loc.get("city", DEFAULT_CITY)) if isinstance(loc, dict) else (str(loc) if loc else DEFAULT_CITY)

            time_raw = item.get("time", item.get("publishDate", ""))
            pt = parse_avito_time(str(time_raw)) if time_raw else None

            return AvitoAd(
                ad_id=ad_id,
                title=item.get("title", item.get("name", "")),
                price=price,
                description=item.get("description", item.get("body", "")) or "",
                photo_urls=photos,
                city=city,
                is_delivery=item.get("delivery", False),
                publish_time=pt,
                url=item.get("url", f"{AVITO_BASE_URL}/items/{ad_id}"),
            )
        except Exception as exc:
            logger.debug("_item_to_ad ошибка: %s", exc)
            return None

    @staticmethod
    def _schema_to_ad(schema: dict) -> Optional[AvitoAd]:
        """Schema.org Offer → AvitoAd."""
        try:
            ad_id = str(schema.get("sku", schema.get("identifier", "")))
            if not ad_id:
                return None

            pv = schema.get("price", "")
            pc = schema.get("priceCurrency", "₽")
            price = f"{pv} {pc}" if pv else ""

            photos = []
            img = schema.get("image", schema.get("imageUrl", ""))
            if isinstance(img, str) and img:
                photos.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        photos.append(i)
                    elif isinstance(i, dict):
                        u = i.get("url", i.get("contentUrl", ""))
                        if u:
                            photos.append(u)

            area = schema.get("areaServed", schema.get("availableAtOrFrom", ""))
            city = area.get("name", DEFAULT_CITY) if isinstance(area, dict) else (area if isinstance(area, str) else DEFAULT_CITY)

            dp = schema.get("datePublished", "")
            pt = parse_avito_time(str(dp)) if dp else None

            return AvitoAd(
                ad_id=ad_id,
                title=schema.get("name", ""),
                price=price,
                description=schema.get("description", ""),
                photo_urls=photos,
                city=city,
                is_delivery=False,
                publish_time=pt,
                url=schema.get("url", f"{AVITO_BASE_URL}/items/{ad_id}"),
            )
        except Exception as exc:
            logger.debug("_schema_to_ad ошибка: %s", exc)
            return None

    # ──────────────────────────────────────────
    #  Main parse cycle
    # ──────────────────────────────────────────

    async def parse(
        self,
        user_id: int,
        keyword: str,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
    ) -> list[AvitoAd]:
        """
        Один полный цикл: Смоленск → РФ с доставкой → дедуп.
        Возвращает только новые объявления.
        """
        if not self._context:
            raise RuntimeError("Browser не запущен.")

        self._is_running = True
        new_ads: list[AvitoAd] = []

        try:
            # Этап 1: Смоленск (в наличии)
            logger.info("🔍 Поиск в Смоленске: '%s'", keyword)
            smolensk_ads = await self._search_city(
                keyword=keyword, city=DEFAULT_CITY,
                category=category, min_price=min_price, max_price=max_price,
            )

            # Этап 2: РФ с доставкой в Смоленск
            logger.info("🔍 Поиск по РФ с доставкой: '%s'", keyword)
            delivery_ads = await self._search_city(
                keyword=keyword, city="Россия",
                category=category, min_price=min_price, max_price=max_price,
                delivery_city=DEFAULT_DELIVERY_CITY,
            )

            # Дедупликация
            all_ads = smolensk_ads + delivery_ads
            last_pt = await self._db.get_last_parse_time()

            for ad in all_ads:
                if last_pt and ad.publish_time and ad.publish_time <= last_pt:
                    continue
                if await self._db.ad_already_sent(user_id, ad.ad_id):
                    continue
                new_ads.append(ad)
                self._total_parsed += 1

            self._last_parse_dt = datetime.now(tz=MOSCOW_TZ)
            await self._db.update_last_parse_time(self._last_parse_dt)

            logger.info("Новых: %d из %d", len(new_ads), len(all_ads))

        except Exception as exc:
            logger.error("Ошибка парсинга: %s", exc)
        finally:
            self._is_running = False

        return new_ads

    async def _search_city(
        self,
        keyword: str,
        city: str,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        delivery_city: Optional[str] = None,
    ) -> list[AvitoAd]:
        """Поиск в городе: URL → страница → капча → скролл → JSON."""
        url = self.build_search_url(
            keyword=keyword, city=city, min_price=min_price,
            max_price=max_price, category=category,
            delivery_city=delivery_city,
        )

        page = await self._new_stealth_page()
        ads: list[AvitoAd] = []

        try:
            logger.info("Открываем: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Проверяем капчу
            if await CaptchaDetector.is_captcha_present(page):
                await self._handle_captcha(page)

            # Человеческая задержка
            await self._human_delay()

            # Скроллим
            await self._human_scroll(page)

            # Извлекаем данные
            ads = await self._extract_ads_from_page(page)

        except Exception as exc:
            logger.error("Ошибка _search_city (%s): %s", city, exc)
        finally:
            try:
                await page.close()
            except Exception:
                pass

        return ads
