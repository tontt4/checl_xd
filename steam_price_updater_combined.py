"""
Steam Price Updater Plugin - Об'єднана версія у одному файлі
Автоматическое обновление цен лотов на основе Steam API с выбором валют

Версія: 2.1.0 (combined)
Автор: @humblegodq  
UUID: 247153d9-f732-4f01-a11f-a3945b68b533

Цей файл містить весь код плагину в одному файлі для зручності використання.
Всі модулі з steam_price_updater/ об'єднані в одному місці.
"""

from __future__ import annotations
import atexit
import json
import os
import time
import threading
import logging
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime as dt
from typing import Dict, Any, Optional, List, Union, Tuple, TYPE_CHECKING
from threading import Lock

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import telebot

if TYPE_CHECKING:
    from cardinal import Cardinal
    from tg_bot import CBT
else:
    from tg_bot import CBT

# Налаштування логування
logger = logging.getLogger("FPC.steam_price_updater")

# ===== КОНСТАНТИ ТА КОНФІГУРАЦІЯ =====

NAME = "Steam Price Updater"
VERSION = "2.1.0"
DESCRIPTION = "Автоматическое обновление цен лотов на основе Steam API с выбором валют"
CREDITS = "@humblegodq"
UUID = "247153d9-f732-4f01-a11f-a3945b68b533"
SETTINGS_PAGE = True

LOGGER_PREFIX = "[STEAM PRICE UPDATER]"

class Config:
    """Конфігурація плагіну"""
    # Кеширование
    CACHE_TTL = 3600  # 1 час
    
    # Циклы и задержки
    CYCLE_PAUSE = 300  # 5 минут
    LOT_PROCESSING_DELAY = 2  # 2 секунди між лотами
    
    # Пагинация
    LOTS_PER_PAGE = 8
    
    # Steam API
    STEAM_REQUEST_DELAY = 10  # 10 секунд між запитами
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 15
    
    # Валюти
    DEFAULT_STEAM_CURRENCY = "UAH"
    SUPPORTED_CURRENCIES = ["UAH", "KZT", "RUB", "USD", "EUR"]
    ACCOUNT_CURRENCIES = ["USD", "RUB", "EUR"]
    
    # Кеш
    MAX_CACHE_SIZE = 1000

# Налаштування за замовчуванням
DEFAULT_SETTINGS = {
    "currency": "USD",
    "account_currency": "USD", 
    "time": 21600,  # 6 годин
    "first_markup": 3.0,  # Наценка на валютний курс
    "second_markup": 5.0,  # Маржа прибутку
    "fixed_markup": 0.5,  # Фіксована наценка
    "max_price": 5000.0,
    "min_price": 1.0,
    "round_to_integer": False,
    "steam_request_delay": Config.STEAM_REQUEST_DELAY,
    "request_timeout": Config.REQUEST_TIMEOUT
}

# Callback кнопки
class CallbackButtons:
    CHANGE_CURRENCY = "SPU_change_curr"
    TEXT_CHANGE_LOT = "SPU_ChangeLot"
    TEXT_EDIT = "SPU_Edit"
    TEXT_DELETE = "SPU_DELETE"
    UPDATE_NOW = "SPU_UpdateNow"
    STATS = "SPU_Stats"
    SHOW_SETTINGS = "SPU_show_settings"
    CHANGE_STEAM_CURRENCY = "SPU_change_steam_curr"
    LOTS_MENU = "SPU_lots_menu"
    EDIT_LOT = "SPU_edit_lot"
    TOGGLE_LOT = "SPU_toggle_lot"
    DELETE_LOT = "SPU_delete_lot"
    REFRESH_RATES = "SPU_refresh_rates"
    SWITCH_PRICE_TYPE = "SPU_switch_price_type"

# ===== МЕНЕДЖЕР НАЛАШТУВАНЬ =====

class SettingsManager:
    """Менеджер налаштувань"""
    
    def __init__(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.settings_file = "storage/plugins/steam_price_updater.json"
    
    def load_settings(self):
        """Завантажує налаштування з файлу"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        loaded_settings = json.loads(content)
                        self.settings.update(loaded_settings)
                        logger.info(f"{LOGGER_PREFIX} Налаштування завантажено")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка завантаження налаштувань: {e}")
    
    def save_settings(self):
        """Зберігає налаштування у файл"""
        try:
            os.makedirs("storage/plugins", exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.settings, indent=4, ensure_ascii=False))
            logger.info(f"{LOGGER_PREFIX} Налаштування збережено")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка збереження налаштувань: {e}")
    
    def get(self, key: str, default=None):
        """Отримує значення налаштування"""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """Встановлює значення налаштування"""
        self.settings[key] = value
    
    def update(self, new_settings: Dict[str, Any]):
        """Оновлює налаштування"""
        self.settings.update(new_settings)

# ===== СИСТЕМА КЕШУВАННЯ =====

class UnifiedCache:
    """Єдина система кешування"""
    
    def __init__(self, max_size: int = Config.MAX_CACHE_SIZE, ttl: int = Config.CACHE_TTL):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Отримує значення з кешу з перевіркою TTL"""
        with self._lock:
            if key in self.cache:
                entry = self.cache[key]
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["value"]
                else:
                    # Видаляємо застарілий запис
                    try:
                        del self.cache[key]
                    except KeyError:
                        pass
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Встановлює значення в кеш"""
        with self._lock:
            # Очищуємо місце якщо кеш переповнений
            if len(self.cache) >= self.max_size:
                try:
                    oldest_key = min(self.cache.keys(), 
                                   key=lambda k: self.cache[k]["timestamp"])
                    del self.cache[oldest_key]
                except (ValueError, KeyError):
                    pass
            
            self.cache[key] = {
                "value": value,
                "timestamp": time.time()
            }
    
    def has(self, key: str) -> bool:
        """Перевіряє наявність ключа в кеші"""
        return self.get(key) is not None
    
    def clear(self) -> None:
        """Очищує весь кеш"""
        with self._lock:
            self.cache.clear()
    
    def clear_expired(self) -> int:
        """Очищує застарілі записи"""
        with self._lock:
            current_time = time.time()
            expired_keys = [k for k, v in self.cache.items() 
                           if current_time - v["timestamp"] >= self.ttl]
            for key in expired_keys:
                try:
                    del self.cache[key]
                except KeyError:
                    pass
            return len(expired_keys)
    
    def size(self) -> int:
        """Повертає розмір кешу"""
        with self._lock:
            return len(self.cache)
    
    def clear_pattern(self, pattern: str) -> int:
        """Очищує записи за шаблоном"""
        with self._lock:
            matching_keys = [k for k in self.cache.keys() if pattern in k]
            for key in matching_keys:
                try:
                    del self.cache[key]
                except KeyError:
                    pass
            return len(matching_keys)

class CacheManager:
    """Менеджер кешу зі спеціалізованими методами"""
    
    def __init__(self):
        self.cache = UnifiedCache()
    
    def get_steam_price(self, steam_id: str, currency: str) -> Optional[float]:
        """Отримує ціну Steam з кешу"""
        key = f"steam_price_{steam_id}_{currency}"
        cached_data = self.cache.get(key)
        if cached_data and isinstance(cached_data, dict):
            return cached_data.get("price")
        return None
    
    def set_steam_price(self, steam_id: str, currency: str, price: float) -> None:
        """Зберігає ціну Steam в кеш"""
        key = f"steam_price_{steam_id}_{currency}"
        self.cache.set(key, {"price": price})
        logger.debug(f"{LOGGER_PREFIX} Ціна Steam закешована: {steam_id} = {price} {currency}")
    
    def get_currency_rate(self, currency: str) -> Optional[Dict[str, Any]]:
        """Отримує курс валюти з кешу"""
        key = f"currency_rate_{currency}"
        return self.cache.get(key)
    
    def set_currency_rate(self, currency: str, rate: float, source: str = "unknown") -> None:
        """Зберігає курс валюти в кеш"""
        key = f"currency_rate_{currency}"
        data = {
            "rate": rate,
            "timestamp": time.time(),
            "source": source
        }
        self.cache.set(key, data)
        logger.debug(f"{LOGGER_PREFIX} Курс валюти закешовано: USD/{currency} = {rate} ({source})")
    
    def get_game_name(self, steam_id: str) -> Optional[str]:
        """Отримує назву гри з кешу"""
        key = f"game_name_{steam_id}"
        cached_data = self.cache.get(key)
        if cached_data and isinstance(cached_data, dict):
            return cached_data.get("name")
        return None
    
    def set_game_name(self, steam_id: str, name: str) -> None:
        """Зберігає назву гри в кеш"""
        key = f"game_name_{steam_id}"
        self.cache.set(key, {"name": name})
    
    def clear_currency_cache(self) -> int:
        """Очищає кеш курсів валют"""
        return self.cache.clear_pattern("currency_rate_")
    
    def clear_steam_cache(self) -> int:
        """Очищає кеш цін Steam"""
        return self.cache.clear_pattern("steam_price_")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Повертає статистику кешу"""
        total_size = self.cache.size()
        steam_prices = len([k for k in self.cache.cache.keys() if k.startswith("steam_price_")])
        currency_rates = len([k for k in self.cache.cache.keys() if k.startswith("currency_rate_")])
        game_names = len([k for k in self.cache.cache.keys() if k.startswith("game_name_")])
        
        return {
            "total": total_size,
            "steam_prices": steam_prices,
            "currency_rates": currency_rates,
            "game_names": game_names
        }

# ===== API ДЛЯ КУРСІВ ВАЛЮТ =====

class CurrencyAPI:
    """API для отримання курсів валют"""
    
    # Фіксовані курси як fallback
    FALLBACK_RATES = {
        "UAH": 41.82,
        "RUB": 78.42,
        "KZT": 519.86,
        "EUR": 0.85,
        "USD": 1.0
    }
    
    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
    
    def get_currency_rate(self, currency: str) -> float:
        """Отримує курс валюти USD до вказаної валюти"""
        currency = currency.upper()
        
        # Перевіряємо кеш
        cached_rate = self.cache_manager.get_currency_rate(currency)
        if cached_rate:
            cache_age = time.time() - cached_rate.get("timestamp", 0)
            if cache_age < 900:  # 15 хвилин
                logger.debug(f"{LOGGER_PREFIX} Використовую кеш для USD/{currency}: {cached_rate.get('rate')}")
                return cached_rate.get("rate", self._get_fallback_rate(currency))
        
        # Отримуємо свіжий курс
        rate = self._fetch_fresh_rate(currency)
        if rate:
            self.cache_manager.set_currency_rate(currency, rate, "exchangerate-api")
            return rate
        
        # Використовуємо fallback
        return self._get_fallback_rate(currency)
    
    def _fetch_fresh_rate(self, currency: str) -> Optional[float]:
        """Отримує свіжий курс з API"""
        try:
            # Основний API - exchangerate-api
            logger.debug(f"{LOGGER_PREFIX} Отримую курс USD/{currency} через exchangerate-api")
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(url, timeout=Config.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                rates = data.get("rates", {})
                
                if currency in rates:
                    rate = float(rates[currency])
                    logger.info(f"{LOGGER_PREFIX} Отримано курс USD/{currency}: {rate} (exchangerate-api)")
                    return rate
            
            # Fallback API за валютами
            return self._fetch_fallback_rate(currency)
            
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка отримання курсу USD/{currency}: {e}")
            return self._fetch_fallback_rate(currency)
    
    def _fetch_fallback_rate(self, currency: str) -> Optional[float]:
        """Резервні API для конкретних валют"""
        try:
            if currency == "UAH":
                return self._fetch_uah_rate()
            elif currency == "RUB":
                return self._fetch_rub_rate()
            elif currency == "KZT":
                return self._fetch_kzt_rate()
            elif currency == "EUR":
                return self._fetch_eur_rate()
            else:
                return None
                
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка fallback API для {currency}: {e}")
            return None
    
    def _fetch_uah_rate(self) -> Optional[float]:
        """Отримує курс UAH з НБУ"""
        try:
            nbu_url = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json"
            response = requests.get(nbu_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    rate = float(data[0]["rate"])
                    logger.info(f"{LOGGER_PREFIX} Отримано курс USD/UAH: {rate} (НБУ)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка НБУ API: {e}")
        return None
    
    def _fetch_rub_rate(self) -> Optional[float]:
        """Отримує курс RUB з ЦБ РФ"""
        try:
            cbr_url = "https://www.cbr-xml-daily.ru/daily_json.js"
            response = requests.get(cbr_url, timeout=10)
            if response.status_code == 200:
                cbr_data = response.json()
                usd_data = cbr_data.get("Valute", {}).get("USD", {})
                if usd_data:
                    rate = float(usd_data["Value"])
                    logger.info(f"{LOGGER_PREFIX} Отримано курс USD/RUB: {rate} (ЦБ РФ)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка ЦБ РФ API: {e}")
        return None
    
    def _fetch_kzt_rate(self) -> Optional[float]:
        """Отримує курс KZT з Нацбанку Казахстану"""
        try:
            kz_url = f"https://www.nationalbank.kz/rss/get_rates.cfm?fdate={time.strftime('%d.%m.%Y')}"
            response = requests.get(kz_url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall(".//item"):
                    title = item.find("title")
                    description = item.find("description")
                    if title is not None and "USD" in title.text:
                        rate_text = description.text if description is not None else ""
                        rate_match = re.search(r'(\d+\.?\d*)', rate_text)
                        if rate_match:
                            rate = float(rate_match.group(1))
                            logger.info(f"{LOGGER_PREFIX} Отримано курс USD/KZT: {rate} (Нацбанк КЗ)")
                            return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка API Казахстану: {e}")
        return None
    
    def _fetch_eur_rate(self) -> Optional[float]:
        """Отримує курс EUR через резервний API"""
        try:
            ecb_url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(ecb_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "rates" in data and "EUR" in data["rates"]:
                    rate = data["rates"]["EUR"]
                    logger.info(f"{LOGGER_PREFIX} Отримано курс USD/EUR: {rate} (резервний API)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка резервного API EUR: {e}")
        return None
    
    def _get_fallback_rate(self, currency: str) -> float:
        """Повертає fallback курс з кешу або константи"""
        # Намагаємося знайти старий курс у кеші
        cached_rate = self.cache_manager.get_currency_rate(currency)
        if cached_rate:
            rate = cached_rate.get("rate")
            if rate and rate > 0:
                cache_age = time.time() - cached_rate.get("timestamp", 0)
                hours = int(cache_age / 3600)
                minutes = int((cache_age % 3600) / 60)
                logger.warning(f"{LOGGER_PREFIX} Використовуємо старий курс USD/{currency}: {rate} (вік: {hours}г {minutes}х)")
                return rate
        
        # Використовуємо константний fallback курс
        rate = self.FALLBACK_RATES.get(currency, 1.0)
        logger.warning(f"{LOGGER_PREFIX} Використовуємо екстрений fallback курс USD/{currency}: {rate}")
        return rate
    
    def refresh_all_rates(self) -> dict:
        """Примусово оновлює всі курси валют"""
        results = {}
        
        # Очищуємо кеш курсів
        self.cache_manager.clear_currency_cache()
        
        # Оновлюємо всі підтримувані валюти
        for currency in Config.SUPPORTED_CURRENCIES:
            if currency != "USD":  # USD завжди = 1.0
                try:
                    rate = self.get_currency_rate(currency)
                    results[currency] = rate
                    logger.info(f"{LOGGER_PREFIX} Оновлено курс USD/{currency}: {rate}")
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Помилка оновлення курсу {currency}: {e}")
                    results[currency] = self._get_fallback_rate(currency)
        
        results["USD"] = 1.0
        return results

# ===== STEAM API =====

class SteamAPI:
    """API для роботи зі Steam Store"""
    
    # Карта валют для Steam API
    CURRENCY_MAP = {
        "UAH": "ua",
        "KZT": "kz", 
        "RUB": "ru",
        "USD": "us",
        "EUR": "eu"
    }
    
    def __init__(self, cache_manager, settings_manager):
        self.cache_manager = cache_manager
        self.settings_manager = settings_manager
    
    def validate_steam_id(self, steam_id: str) -> Tuple[bool, str, str]:
        """
        Валідує Steam ID
        Повертає: (is_valid, id_type, clean_id)
        """
        if not steam_id or not str(steam_id).strip():
            return False, "", ""
        
        steam_id = str(steam_id).strip()
        
        # Перевіряємо Sub ID
        if steam_id.startswith("sub_"):
            try:
                sub_id_num = steam_id[4:]
                if sub_id_num.isdigit() and len(sub_id_num) > 0:
                    return True, "sub", sub_id_num
                else:
                    return False, "", ""
            except:
                return False, "", ""
        else:
            # Перевіряємо App ID
            if steam_id.isdigit() and len(steam_id) > 0:
                return True, "app", steam_id
            else:
                return False, "", ""
    
    def get_steam_price(self, steam_id: str, currency_code: str = "UAH") -> Optional[float]:
        """
        Отримує ціну гри/DLC з Steam Store API
        """
        # Валідуємо Steam ID
        is_valid, id_type, clean_id = self.validate_steam_id(steam_id)
        if not is_valid:
            logger.warning(f"{LOGGER_PREFIX} Неправильний формат Steam ID: {steam_id}")
            return None
        
        # Отримуємо код країни для API
        cc_code = self.CURRENCY_MAP.get(currency_code, "ua")
        
        # Перевіряємо кеш
        cached_price = self.cache_manager.get_steam_price(steam_id, currency_code)
        if cached_price is not None:
            logger.debug(f"{LOGGER_PREFIX} Кешована ціна для Steam {steam_id} ({currency_code})")
            return cached_price
        
        # Отримуємо ціну з API
        price = self._fetch_price_from_api(id_type, clean_id, cc_code)
        
        if price is not None:
            # Кешуємо результат
            self.cache_manager.set_steam_price(steam_id, currency_code, price)
            logger.debug(f"{LOGGER_PREFIX} Steam ціна для {steam_id}: {price} {currency_code}")
        
        return price
    
    def _fetch_price_from_api(self, id_type: str, clean_id: str, cc_code: str) -> Optional[float]:
        """Отримує ціну з Steam API"""
        try:
            # Затримка між запитами
            time.sleep(self.settings_manager.get("steam_request_delay", Config.STEAM_REQUEST_DELAY))
            
            if id_type == "sub":
                return self._fetch_package_price(clean_id, cc_code)
            else:
                return self._fetch_app_price(clean_id, cc_code)
                
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка отримання Steam ціни для {clean_id} ({cc_code}): {e}")
            return None
    
    def _fetch_package_price(self, package_id: str, cc_code: str) -> Optional[float]:
        """Отримує ціну пакету (Sub ID)"""
        url = f"https://store.steampowered.com/api/packagedetails/?packageids={package_id}&cc={cc_code}"
        response = requests.get(url, timeout=self.settings_manager.get("request_timeout", Config.REQUEST_TIMEOUT))
        
        if response.status_code == 200:
            data = response.json()
            package_data = data.get(str(package_id))
            
            if package_data and package_data.get("success"):
                price_overview = package_data.get("data", {}).get("price")
                
                if price_overview:
                    final_price = price_overview.get("final", 0)
                    if final_price > 0:
                        return final_price / 100.0
                
                # Безкоштовний контент
                return 0.0
        
        return None
    
    def _fetch_app_price(self, app_id: str, cc_code: str) -> Optional[float]:
        """Отримує ціну додатку (App ID)"""
        url = f"https://store.steampowered.com/api/appdetails/?appids={app_id}&cc={cc_code}&filters=price_overview"
        response = requests.get(url, timeout=self.settings_manager.get("request_timeout", Config.REQUEST_TIMEOUT))
        
        if response.status_code == 200:
            data = response.json()
            app_data = data.get(str(app_id))
            
            if app_data and app_data.get("success"):
                price_overview = app_data.get("data", {}).get("price_overview")
                
                if price_overview:
                    final_price = price_overview.get("final", 0)
                    if final_price > 0:
                        return final_price / 100.0
                
                # Безкоштовна гра
                return 0.0
        
        return None
    
    def get_game_name(self, steam_id: str) -> str:
        """Отримує назву гри з Steam API"""
        if not steam_id:
            return "Невідома гра"
        
        # Перевіряємо кеш
        cached_name = self.cache_manager.get_game_name(steam_id)
        if cached_name:
            return cached_name
        
        # Отримуємо назву з API
        name = self._fetch_game_name_from_api(steam_id)
        
        if name:
            self.cache_manager.set_game_name(steam_id, name)
            return name
        
        return f"Steam {steam_id}"
    
    def _fetch_game_name_from_api(self, steam_id: str) -> Optional[str]:
        """Отримує назву гри з Steam API"""
        try:
            is_sub_id = str(steam_id).startswith("sub_")
            
            if is_sub_id:
                # Package details
                sub_id = str(steam_id)[4:]
                url = "https://store.steampowered.com/api/packagedetails"
                params = {"packageids": sub_id, "filters": "basic"}
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    package_data = data.get(str(sub_id), {})
                    if package_data.get("success") and "data" in package_data:
                        return package_data["data"].get("name", f"Sub {steam_id}")
            else:
                # App details
                url = "https://store.steampowered.com/api/appdetails"
                params = {"appids": steam_id, "filters": "basic"}
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    app_data = data.get(str(steam_id), {})
                    if app_data.get("success") and "data" in app_data:
                        return app_data["data"].get("name", f"App {steam_id}")
                        
        except Exception as e:
            logger.debug(f"{LOGGER_PREFIX} Помилка отримання назви гри {steam_id}: {e}")
        
        return None

# ===== КАЛЬКУЛЯТОР ЦІН =====

class PriceCalculator:
    """Калькулятор цін для лотів"""
    
    def __init__(self, currency_api, settings_manager):
        self.currency_api = currency_api
        self.settings_manager = settings_manager
    
    def calculate_lot_price(self, steam_price: Union[float, int, str], steam_currency: str = "UAH") -> float:
        """
        Обчислює ціну лота з урахуванням валюти FunPay акаунта
        
        Логіка наценки:
        - first_markup% наценка на валютний курс
        - second_markup% маржа прибутку  
        - fixed_markup одиниць валюти фіксована наценка
        """
        # Валідація вхідних даних
        try:
            if isinstance(steam_price, str):
                steam_price = float(steam_price)
            elif not isinstance(steam_price, (int, float)):
                logger.warning(f"{LOGGER_PREFIX} Неправильний тип даних для steam_price: {type(steam_price)}")
                return 0.0
            
            steam_price = float(steam_price)
            if steam_price < 0:
                logger.warning(f"{LOGGER_PREFIX} Від'ємна ціна Steam: {steam_price}")
                return 0.0
                
        except (ValueError, TypeError) as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка перетворення steam_price: {e}")
            return 0.0
        
        # Мінімальна ціна для безкоштовних ігор
        if steam_price <= 0.01:
            return self.settings_manager.get("min_price", 1.0)
        
        try:
            # Отримуємо валюту акаунта
            account_currency = self.settings_manager.get("currency", "USD")
            
            # Конвертуємо ціну у валюту акаунта
            base_price = self._convert_to_account_currency(steam_price, steam_currency, account_currency)
            
            if base_price <= 0:
                logger.error(f"{LOGGER_PREFIX} Помилка конвертації валюти")
                return 0.0
            
            # Застосовуємо наценки
            final_price = self._apply_markups(base_price)
            
            # Застосовуємо обмеження за ціною
            final_price = self._apply_price_limits(final_price)
            
            # Округлюємо до 2 знаків
            final_price = round(final_price, 2)
            
            # Логуємо розрахунок
            currency_symbol = {"USD": "$", "RUB": "₽", "EUR": "€"}.get(account_currency, account_currency)
            logger.debug(f"{LOGGER_PREFIX} Розрахунок ціни: {steam_price} {steam_currency} → {base_price:.4f} {account_currency} → {currency_symbol}{final_price:.2f}")
            
            return final_price
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка розрахунку ціни: {e}")
            return 0.0
    
    def _convert_to_account_currency(self, steam_price: float, steam_currency: str, account_currency: str) -> float:
        """Конвертує ціну Steam у валюту акаунта"""
        
        # Якщо валюти однакові, конвертація не потрібна
        if steam_currency == account_currency:
            return steam_price
        
        # Конвертуємо через USD як базову валюту
        if account_currency == "USD":
            # Steam currency → USD
            if steam_currency == "USD":
                return steam_price
            else:
                currency_rate = self.currency_api.get_currency_rate(steam_currency)
                if currency_rate <= 0:
                    logger.warning(f"{LOGGER_PREFIX} Неправильний курс валюти: {currency_rate}")
                    return 0.0
                return steam_price / currency_rate
        else:
            # Steam currency → USD → Account currency
            if steam_currency == "USD":
                price_usd = steam_price
            else:
                steam_rate = self.currency_api.get_currency_rate(steam_currency)
                if steam_rate <= 0:
                    logger.warning(f"{LOGGER_PREFIX} Неправильний курс Steam валюти: {steam_rate}")
                    return 0.0
                price_usd = steam_price / steam_rate
            
            # USD → Account currency
            account_rate = self.currency_api.get_currency_rate(account_currency)
            if account_rate <= 0:
                logger.warning(f"{LOGGER_PREFIX} Неправильний курс валюти акаунта: {account_rate}")
                return 0.0
            return price_usd * account_rate
    
    def _apply_markups(self, base_price: float) -> float:
        """Застосовує наценки до базової ціни"""
        
        # Наценка на валютний курс
        first_markup = self.settings_manager.get("first_markup", 3.0)
        price_with_currency_markup = base_price * (1 + first_markup / 100)
        
        # Маржа прибутку + фіксована наценка
        second_markup = self.settings_manager.get("second_markup", 5.0)
        fixed_markup = self.settings_manager.get("fixed_markup", 0.5)
        final_price = price_with_currency_markup * (1 + second_markup / 100) + fixed_markup
        
        return final_price
    
    def _apply_price_limits(self, price: float) -> float:
        """Застосовує обмеження за мінімальною та максимальною ціною"""
        min_price = self.settings_manager.get("min_price", 1.0)
        max_price = self.settings_manager.get("max_price", 5000.0)
        
        return max(min_price, min(price, max_price))

# ===== МЕНЕДЖЕР ЛОТІВ =====

class LotManager:
    """Менеджер лотів"""
    
    def __init__(self, steam_api, price_calculator, settings_manager):
        self.lots = {}
        self.lots_file = "storage/plugins/steam_price_updater_lots.json"
        self.wizard_states = {}
        self.wizard_file = "storage/plugins/steam_price_updater_wizard.json"
        self.steam_api = steam_api
        self.price_calculator = price_calculator
        self.settings_manager = settings_manager
    
    def load_lots(self) -> None:
        """Завантажує лоти з файлу"""
        load_attempts = [
            ("storage/plugins/steam_price_updater_lots.json", "основне розташування"),
            ("steam_price_updater_lots.json", "поточна директорія"),
            ("/tmp/steam_price_updater_lots.json", "тимчасова директорія"),
            ("./lots_backup.json", "резервна копія")
        ]
        
        lots_file = None
        for attempt_file, description in load_attempts:
            if os.path.exists(attempt_file):
                lots_file = attempt_file
                logger.info(f"{LOGGER_PREFIX} Знайдено файл лотів: {lots_file} ({description})")
                break
        
        if lots_file:
            try:
                with open(lots_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        self.lots = json.loads(content)
                        
                        # Міграція старих даних
                        self._migrate_lot_data()
                        
                        logger.info(f"{LOGGER_PREFIX} Завантажено {len(self.lots)} лотів")
                    else:
                        self.lots = {}
            except Exception as e:
                logger.warning(f"{LOGGER_PREFIX} Помилка завантаження лотів: {e}")
                self.lots = {}
        else:
            logger.info(f"{LOGGER_PREFIX} Файл лотів не знайдено, створюємо новий")
            self.lots = {}
    
    def _migrate_lot_data(self) -> None:
        """Міграція старих даних лотів"""
        for lot_id, lot_data in self.lots.items():
            # Міграція steam_app_id → steam_id
            if "steam_id" not in lot_data and "steam_app_id" in lot_data:
                self.lots[lot_id]["steam_id"] = str(lot_data["steam_app_id"])
            
            # Встановлення значень за замовчуванням
            defaults = {
                "steam_app_id": 0,
                "steam_id": "730",
                "steam_currency": "UAH",
                "min": self.settings_manager.get("min_price", 1.0),
                "max": self.settings_manager.get("max_price", 5000.0),
                "last_steam_price": 0,
                "last_price": 0,
                "last_update": 0,
                "on": True
            }
            
            for key, default_value in defaults.items():
                if key not in lot_data:
                    self.lots[lot_id][key] = default_value
    
    def save_lots(self) -> bool:
        """Зберігає лоти у файл"""
        try:
            logger.debug(f"{LOGGER_PREFIX} Збереження {len(self.lots)} лотів")
            
            # Підготовка даних
            json_data = json.dumps(self.lots, indent=4, ensure_ascii=False)
            
            # Спроби збереження
            save_attempts = [
                ("storage/plugins/steam_price_updater_lots.json", "основне розташування"),
                ("steam_price_updater_lots.json", "поточна директорія"),
                ("/tmp/steam_price_updater_lots.json", "тимчасова директорія"),
                ("./lots_backup.json", "резервна копія")
            ]
            
            for attempt_file, description in save_attempts:
                try:
                    # Створюємо директорію якщо потрібно
                    if "/" in attempt_file:
                        dir_path = os.path.dirname(attempt_file)
                        if dir_path and not os.path.exists(dir_path):
                            os.makedirs(dir_path, exist_ok=True)
                    
                    # Зберігаємо файл
                    with open(attempt_file, "w", encoding="utf-8") as f:
                        f.write(json_data)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except (OSError, AttributeError):
                            pass
                    
                    # Перевіряємо що файл створився
                    if os.path.exists(attempt_file):
                        file_size = os.path.getsize(attempt_file)
                        logger.info(f"{LOGGER_PREFIX} ✅ Лоти збережено у {attempt_file} (розмір: {file_size} байт)")
                        return True
                        
                except (PermissionError, OSError, IOError) as e:
                    logger.warning(f"{LOGGER_PREFIX} Не вдалося зберегти у {attempt_file}: {e}")
                    continue
            
            logger.error(f"{LOGGER_PREFIX} ❌ Не вдалося зберегти лоти в жодне розташування!")
            return False
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} ❌ Критична помилка збереження лотів: {e}")
            return False
    
    def validate_lot_data(self, lot_data: Dict[str, Any]) -> bool:
        """Валідує дані лота"""
        required_fields = ["steam_id", "steam_currency", "min", "max"]
        
        # Перевіряємо обов'язкові поля
        for field in required_fields:
            if field not in lot_data:
                logger.debug(f"{LOGGER_PREFIX} Відсутнє поле: {field}")
                return False
        
        # Перевіряємо Steam ID
        steam_id = lot_data.get("steam_id")
        if not steam_id or steam_id == "":
            logger.debug(f"{LOGGER_PREFIX} Порожній steam_id")
            return False
        
        # Перевіряємо ціни
        min_price = lot_data.get("min")
        max_price = lot_data.get("max")
        
        if not isinstance(min_price, (int, float)) or not isinstance(max_price, (int, float)):
            logger.debug(f"{LOGGER_PREFIX} Неправильний тип цін")
            return False
        
        if min_price <= 0 or max_price <= 0:
            logger.debug(f"{LOGGER_PREFIX} Від'ємні ціни")
            return False
        
        if min_price > max_price:
            logger.debug(f"{LOGGER_PREFIX} min більше max")
            return False
        
        return True
    
    def add_lot(self, lot_id: str, steam_id: str, steam_currency: str, min_price: float, max_price: float) -> bool:
        """Додає новий лот"""
        try:
            # Валідуємо Steam ID
            is_valid, id_type, clean_id = self.steam_api.validate_steam_id(steam_id)
            if not is_valid:
                logger.warning(f"{LOGGER_PREFIX} Неправильний Steam ID: {steam_id}")
                return False
            
            # Створюємо лот
            self.lots[lot_id] = {
                "on": True,
                "steam_id": steam_id,
                "steam_app_id": 0 if steam_id.startswith("sub_") else int(clean_id),
                "steam_currency": steam_currency,
                "min": min_price,
                "max": max_price,
                "last_steam_price": 0,
                "last_price": 0,
                "last_update": 0
            }
            
            logger.info(f"{LOGGER_PREFIX} Додано лот {lot_id}: {steam_id} ({steam_currency})")
            return self.save_lots()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка додавання лота: {e}")
            return False
    
    def update_lot_price(self, lot_id: str, cardinal) -> bool:
        """Оновлює ціну лота"""
        try:
            if lot_id not in self.lots:
                logger.warning(f"{LOGGER_PREFIX} Лот {lot_id} не знайдено")
                return False
            
            lot_data = self.lots[lot_id]
            
            # Валідація даних лота
            if not self.validate_lot_data(lot_data):
                logger.warning(f"{LOGGER_PREFIX} Невалідні дані лота {lot_id}")
                return False
            
            # Отримуємо дані лота
            steam_id = lot_data.get("steam_id")
            steam_currency = lot_data.get("steam_currency", "UAH")
            
            # Отримуємо ціну Steam з повторними спробами
            steam_price = None
            for attempt in range(Config.MAX_RETRIES):
                steam_price = self.steam_api.get_steam_price(steam_id, steam_currency)
                if steam_price and steam_price > 0:
                    break
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.LOT_PROCESSING_DELAY)
            
            if not steam_price or steam_price <= 0:
                logger.warning(f"{LOGGER_PREFIX} Не вдалося отримати ціну Steam для лота {lot_id}")
                return False
            
            # Розраховуємо нову ціну
            new_price = self.price_calculator.calculate_lot_price(steam_price, steam_currency)
            if new_price <= 0:
                logger.error(f"{LOGGER_PREFIX} Неправильна обчислена ціна для лота {lot_id}: {new_price}")
                return False
            
            # Застосовуємо обмеження лота
            lot_min = lot_data.get("min", self.settings_manager.get("min_price", 1.0))
            lot_max = lot_data.get("max", self.settings_manager.get("max_price", 5000.0))
            new_price = max(lot_min, min(new_price, lot_max))
            
            # Оновлюємо ціну через Cardinal API
            success = self._change_cardinal_price(cardinal, lot_id, new_price)
            if success:
                # Оновлюємо дані лота
                self.lots[lot_id]["last_steam_price"] = steam_price
                self.lots[lot_id]["last_price"] = new_price
                self.lots[lot_id]["last_update"] = time.time()
                
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} оновлено: Steam {steam_price} {steam_currency} → ${new_price:.2f}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка оновлення лота {lot_id}: {e}")
            return False
    
    def _change_cardinal_price(self, cardinal, lot_id: str, new_price: float) -> bool:
        """Змінює ціну через Cardinal API"""
        try:
            # Отримуємо поля лота
            lot_fields = cardinal.account.get_lot_fields(int(lot_id))
            if lot_fields is None:
                logger.error(f"{LOGGER_PREFIX} Лот {lot_id} не знайдено у Cardinal")
                # Видаляємо недоступний лот
                if lot_id in self.lots:
                    del self.lots[lot_id]
                    self.save_lots()
                return False
            
            # Перевіряємо поточну ціну
            old_price = lot_fields.price
            if old_price is None:
                logger.error(f"{LOGGER_PREFIX} Поточна ціна лота {lot_id} дорівнює None")
                return False
            
            logger.debug(f"{LOGGER_PREFIX} Лот {lot_id}: поточна ціна {old_price:.2f}, нова {new_price:.2f}")
            
            # Оновлюємо тільки якщо ціна реально змінилася
            if abs(round(new_price, 2) - round(old_price, 2)) >= 0.005:
                lot_fields.price = new_price
                cardinal.account.save_lot(lot_fields)
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} оновлено: {old_price:.2f} → {new_price:.2f}")
                return True
            else:
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} залишився на {old_price:.2f}")
                return True
                
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка зміни ціни лота {lot_id}: {e}")
            return False
    
    def get_lot(self, lot_id: str) -> Optional[Dict[str, Any]]:
        """Отримує дані лота"""
        return self.lots.get(lot_id)
    
    def delete_lot(self, lot_id: str) -> bool:
        """Видаляє лот"""
        if lot_id in self.lots:
            del self.lots[lot_id]
            logger.info(f"{LOGGER_PREFIX} Лот {lot_id} видалено")
            return self.save_lots()
        return False
    
    def get_active_lots(self) -> List[str]:
        """Повертає список активних лотів"""
        return [lot_id for lot_id, lot_data in self.lots.items()
                if lot_data.get("on", False) and lot_id != "0"]
    
    def get_lots_stats(self) -> Dict[str, int]:
        """Повертає статистику лотів"""
        total = len(self.lots)
        active = len(self.get_active_lots())
        with_prices = len([l for l in self.lots.values() if l.get("last_price", 0) > 0])
        
        return {
            "total": total,
            "active": active,
            "with_prices": with_prices
        }

# ===== СПРОЩЕНИЙ TELEGRAM HANDLERS =====

class TelegramHandlers:
    """Обробники Telegram інтерфейсу (спрощена версія)"""
    
    def __init__(self):
        self.bot = None
        self.tg = None
    
    def setup(self, cardinal, lot_manager, lot_updater, currency_api, steam_api, cache_manager, settings_manager):
        """Налаштування обробників"""
        if not cardinal.telegram:
            logger.warning(f"{LOGGER_PREFIX} Telegram бот не включено в FunPayCardinal")
            return
        
        self.tg = cardinal.telegram
        self.bot = self.tg.bot
        self.lot_manager = lot_manager
        self.lot_updater = lot_updater
        self.currency_api = currency_api
        self.steam_api = steam_api
        self.cache_manager = cache_manager
        self.settings_manager = settings_manager
        
        logger.info(f"{LOGGER_PREFIX} Налаштування Telegram обробників...")
        
        # Реєструємо основні обробники
        self.tg.cbq_handler(self.open_settings, lambda c: c.data and c.data.startswith(f"{CBT.PLUGIN_SETTINGS}:{UUID}"))
        self.tg.cbq_handler(self.show_lots_menu, lambda c: c.data and c.data.startswith(CallbackButtons.LOTS_MENU))
        self.tg.cbq_handler(self.update_now, lambda c: c.data and c.data.startswith(CallbackButtons.UPDATE_NOW))
        self.tg.cbq_handler(self.show_stats, lambda c: c.data and c.data.startswith(CallbackButtons.STATS))
        
        logger.info(f"{LOGGER_PREFIX} Telegram обробники налаштовано")
    
    def open_settings(self, call: telebot.types.CallbackQuery) -> None:
        """Головне меню плагіну"""
        try:
            # Перезавантажуємо лоти
            self.lot_manager.load_lots()
            
            keyboard = K()
            
            # Основні кнопки
            keyboard.row(
                B("📦 Лоти", callback_data=f"{CallbackButtons.LOTS_MENU}:0"),
                B("🔄 Оновити зараз", callback_data=f"{CallbackButtons.UPDATE_NOW}:")
            )
            
            keyboard.row(
                B("📊 Статистика", callback_data=f"{CallbackButtons.STATS}:"),
                B("◀ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:0")
            )
            
            # Статистика
            stats = self.lot_manager.get_lots_stats()
            active_lots = stats["active"]
            total_lots = stats["total"]
            
            text = f"🎮 <b>Steam Price Updater v{VERSION}</b>\n\n"
            
            if total_lots == 0:
                text += f"📦 <b>Лоти:</b> Не додано\n"
            else:
                text += f"📦 <b>Лоти:</b> {total_lots} всього, {active_lots} активних\n"
            
            hours = self.settings_manager.get('time', 21600) // 3600
            text += f"⏱ <b>Інтервал:</b> {hours} г\n"
            text += f"💰 <b>Валюта:</b> {self.settings_manager.get('currency', 'USD')}\n\n"
            
            # Курси валют
            text += "<b>💱 Курси валют (USD до місцевої):</b>\n"
            try:
                uah_rate = self.currency_api.get_currency_rate("UAH")
                rub_rate = self.currency_api.get_currency_rate("RUB")
                kzt_rate = self.currency_api.get_currency_rate("KZT")
                
                text += f"🇺🇦 UAH: {uah_rate:.2f}\n"
                text += f"🇷🇺 RUB: {rub_rate:.2f}\n"
                text += f"🇰🇿 KZT: {kzt_rate:.2f}\n"
            except Exception:
                text += f"💰 Курси валют: завантаження...\n"
            
            text += f"📈 Наценка на валютний курс: {self.settings_manager.get('first_markup', 3)}%\n"
            text += f"💸 Маржа: {self.settings_manager.get('second_markup', 5)}% + ${self.settings_manager.get('fixed_markup', 0.5)}"
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка в open_settings: {e}")
            self.bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_lots_menu(self, call: telebot.types.CallbackQuery) -> None:
        """Показує меню управління лотами"""
        try:
            # Перезавантажуємо лоти
            self.lot_manager.load_lots()
            
            stats = self.lot_manager.get_lots_stats()
            text = f"📦 <b>Управління лотами</b>\n\n"
            text += f"📊 <b>Всього:</b> {stats['total']} | <b>Активних:</b> {stats['active']}\n\n"
            
            if stats['total'] == 0:
                text += "📝 <i>Лоти не додано</i>\n\n"
                text += "💡 <b>Для початку роботи:</b>\n"
                text += "1. Додайте лоти через файл конфігурації\n"
                text += "2. Перезапустіть плагін\n"
                text += "3. Лоти почнуть автоматично оновлюватися"
            else:
                text += "<b>Ваші лоти:</b>\n"
                for lot_id, lot_data in list(self.lot_manager.lots.items())[:5]:
                    game_name = self.steam_api.get_game_name(lot_data.get("steam_id", ""))
                    status_icon = "🟢" if lot_data.get("on", False) else "🔴"
                    text += f"{status_icon} {game_name[:25]}...\n"
                
                if len(self.lot_manager.lots) > 5:
                    text += f"... та ще {len(self.lot_manager.lots) - 5} лотів\n"
            
            keyboard = K()
            keyboard.add(B("🔄 Оновити всі", callback_data=f"{CallbackButtons.UPDATE_NOW}:"))
            keyboard.add(B("◀ Головне меню", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка в show_lots_menu: {e}")
            self.bot.answer_callback_query(call.id, "❌ Помилка")
    
    def update_now(self, call: telebot.types.CallbackQuery) -> None:
        """Запускає примусове оновлення всіх лотів"""
        try:
            active_lots = self.lot_manager.get_active_lots()
            
            if not active_lots:
                self.bot.answer_callback_query(call.id, "Немає активних лотів")
                return
            
            self.bot.answer_callback_query(call.id, "Оновлення запущено...")
            
            def update_thread():
                results = self.lot_updater.update_all_lots()
                result_text = f"Оновлення завершено!\nОновлено: {results['updated']}\nПомилок: {results['failed']}"
                self.bot.send_message(call.message.chat.id, result_text)
            
            threading.Thread(target=update_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка в update_now: {e}")
            self.bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_stats(self, call: telebot.types.CallbackQuery) -> None:
        """Показує статистику"""
        try:
            stats = self.lot_manager.get_lots_stats()
            cache_stats = self.cache_manager.get_cache_stats()
            
            text = f"📊 Статистика Steam Price Updater\n\n"
            text += f"📦 Всього лотів: {stats['total']}\n"
            text += f"✅ Активних: {stats['active']}\n"
            text += f"💰 Лотів з цінами: {stats['with_prices']}\n"
            text += f"🔄 Кеш: {cache_stats['total']} записів\n"
            text += f"  • Steam ціни: {cache_stats['steam_prices']}\n"
            text += f"  • Курси валют: {cache_stats['currency_rates']}\n"
            text += f"  • Назви ігор: {cache_stats['game_names']}\n"
            
            # Статус оновлення
            updater_status = self.lot_updater.get_status()
            text += f"\n🔄 Обробник: {'працює' if updater_status['running'] else 'зупинено'}\n"
            
            keyboard = K()
            keyboard.add(B("◀ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка в show_stats: {e}")
            self.bot.answer_callback_query(call.id, "❌ Помилка")

# ===== ОНОВЛЮВАЧ ЛОТІВ =====

class LotUpdater:
    """Основний обробник оновлень лотів"""
    
    def __init__(self, lot_manager, cache_manager, settings_manager):
        self._cardinal = None
        self._running = False
        self._thread = None
        self._last_check_times = {}
        self.lot_manager = lot_manager
        self.cache_manager = cache_manager
        self.settings_manager = settings_manager
    
    def start(self, cardinal) -> None:
        """Запускає основний цикл обробки"""
        if self._running:
            logger.info(f"{LOGGER_PREFIX} Обробник вже запущено")
            return
        
        self._cardinal = cardinal
        self._running = True
        
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"{LOGGER_PREFIX} Запущено основний цикл обробки лотів")
    
    def stop(self) -> None:
        """Зупиняє основний цикл"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"{LOGGER_PREFIX} Основний цикл зупинено")
    
    def _main_loop(self) -> None:
        """Основний цикл обробки лотів"""
        while self._running:
            try:
                current_time = time.time()
                processed_count = 0
                
                active_lots = self.lot_manager.get_active_lots()
                
                for lot_id in active_lots:
                    if not self._running:
                        break
                    
                    if self._should_update_lot(lot_id, current_time):
                        logger.info(f"{LOGGER_PREFIX} Обробляю лот {lot_id}")
                        
                        self._last_check_times[lot_id] = current_time
                        
                        try:
                            success = self.lot_manager.update_lot_price(lot_id, self._cardinal)
                            if success:
                                processed_count += 1
                            
                            time.sleep(Config.LOT_PROCESSING_DELAY)
                            
                        except Exception as e:
                            logger.error(f"{LOGGER_PREFIX} Помилка оновлення лота {lot_id}: {e}")
                
                if processed_count > 0:
                    self.lot_manager.save_lots()
                    logger.info(f"{LOGGER_PREFIX} Цикл завершено, оброблено лотів: {processed_count}")
                
                self._cleanup_cache()
                
            except Exception as e:
                logger.error(f"{LOGGER_PREFIX} Критична помилка в основному циклі: {e}")
            
            time.sleep(Config.CYCLE_PAUSE)
    
    def _should_update_lot(self, lot_id: str, current_time: float) -> bool:
        """Перевіряє чи потрібно оновлювати лот"""
        global_interval = self.settings_manager.get("time", 21600)
        last_check = self._last_check_times.get(lot_id, 0)
        return current_time - last_check >= global_interval
    
    def _cleanup_cache(self) -> None:
        """Очищує застарілий кеш"""
        try:
            expired_count = self.cache_manager.cache.clear_expired()
            if expired_count > 0:
                logger.debug(f"{LOGGER_PREFIX} Очищено {expired_count} застарілих записів кешу")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Помилка очищення кешу: {e}")
    
    def update_lot_now(self, lot_id: str) -> bool:
        """Примусово оновлює конкретний лот"""
        try:
            if not self._cardinal or lot_id not in self.lot_manager.lots:
                return False
            
            success = self.lot_manager.update_lot_price(lot_id, self._cardinal)
            if success:
                self.lot_manager.save_lots()
                self._last_check_times[lot_id] = time.time()
            return success
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Помилка примусового оновлення лота {lot_id}: {e}")
            return False
    
    def update_all_lots(self) -> dict:
        """Примусово оновлює всі активні лоти"""
        results = {"updated": 0, "failed": 0, "total": 0}
        
        if not self._cardinal:
            return results
        
        active_lots = self.lot_manager.get_active_lots()
        results["total"] = len(active_lots)
        
        for lot_id in active_lots:
            try:
                success = self.lot_manager.update_lot_price(lot_id, self._cardinal)
                if success:
                    results["updated"] += 1
                    self._last_check_times[lot_id] = time.time()
                else:
                    results["failed"] += 1
                
                time.sleep(Config.LOT_PROCESSING_DELAY)
                
            except Exception as e:
                logger.error(f"{LOGGER_PREFIX} Помилка оновлення лота {lot_id}: {e}")
                results["failed"] += 1
        
        self.lot_manager.save_lots()
        return results
    
    def get_status(self) -> dict:
        """Повертає статус обробника"""
        return {
            "running": self._running,
            "lots_tracked": len(self._last_check_times),
            "cardinal_available": self._cardinal is not None
        }

# ===== ІНІЦІАЛІЗАЦІЯ ТА ОСНОВНІ ФУНКЦІЇ =====

# Створюємо глобальні екземпляри
settings_manager = SettingsManager()
cache_manager = CacheManager()
currency_api = CurrencyAPI(cache_manager)
steam_api = SteamAPI(cache_manager, settings_manager)
price_calculator = PriceCalculator(currency_api, settings_manager)
lot_manager = LotManager(steam_api, price_calculator, settings_manager)
lot_updater = LotUpdater(lot_manager, cache_manager, settings_manager)
telegram_handlers = TelegramHandlers()

def cleanup_resources():
    """Очистка ресурсів при завершенні"""
    try:
        logger.info(f"{LOGGER_PREFIX} Очистка ресурсів...")
        lot_updater.stop()
        lot_manager.save_lots()
        settings_manager.save_settings()
        cache_manager.cache.clear_expired()
        logger.info(f"{LOGGER_PREFIX} Ресурси очищено")
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Помилка очистки ресурсів: {e}")

def check_cardinal_health(cardinal) -> bool:
    """Перевіряє доступність Cardinal"""
    try:
        return hasattr(cardinal, 'account') and cardinal.account is not None
    except Exception:
        return False

def init(cardinal: Cardinal):
    """Ініціалізація плагіну"""
    try:
        logger.info(f"{LOGGER_PREFIX} Ініціалізація Steam Price Updater v{VERSION}")
        
        if not check_cardinal_health(cardinal):
            logger.error(f"{LOGGER_PREFIX} Cardinal недоступний")
            return
        
        atexit.register(cleanup_resources)
        
        # Завантажуємо налаштування та лоти
        settings_manager.load_settings()
        lot_manager.load_lots()
        
        # Налаштовуємо Telegram обробники
        telegram_handlers.setup(cardinal, lot_manager, lot_updater, currency_api, steam_api, cache_manager, settings_manager)
        
        logger.info(f"{LOGGER_PREFIX} Ініціалізація завершена успішно")
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Критична помилка ініціалізації: {e}")
        raise

def post_start(cardinal: Cardinal):
    """Запуск плагіну після старту Cardinal"""
    try:
        logger.info(f"{LOGGER_PREFIX} Запуск плагіну...")
        
        if not check_cardinal_health(cardinal):
            logger.error(f"{LOGGER_PREFIX} Cardinal недоступний при запуску")
            return
        
        # Запускаємо основний цикл обробки
        lot_updater.start(cardinal)
        
        # Логуємо статистику
        stats = lot_manager.get_lots_stats()
        logger.info(f"{LOGGER_PREFIX} Плагін запущено. Лотів: {stats['total']}, активних: {stats['active']}")
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Помилка запуску плагіну: {e}")

def validate_plugin_integrity():
    """Перевіряє цілісність плагіну"""
    required_components = [
        settings_manager,
        lot_manager, 
        lot_updater,
        cache_manager,
        telegram_handlers
    ]
    
    for component in required_components:
        if component is None:
            logger.error(f"{LOGGER_PREFIX} Відсутній компонент: {component}")
            return False
    
    return True

# Валідація цілісності при імпорті
try:
    if not validate_plugin_integrity():
        raise ImportError("Не вдалося перевірити цілісність плагіну")
    
    logger.info(f"{LOGGER_PREFIX} Плагін завантажено та перевірено")
    
except Exception as e:
    logger.error(f"{LOGGER_PREFIX} Критична помилка завантаження плагіну: {e}")
    raise

# Прив'язка функцій до подій Cardinal
BIND_TO_PRE_INIT = [init]
BIND_TO_POST_START = [post_start]
BIND_TO_DELETE = [cleanup_resources]