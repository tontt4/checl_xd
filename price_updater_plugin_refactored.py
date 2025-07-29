"""
Steam Price Updater Plugin - Refactored Clean Version
Автоматичне оновлення цін лотів на основі Steam API
"""

from __future__ import annotations
import json
import time
import requests
import threading
from threading import Thread, Lock
from typing import TYPE_CHECKING, Optional, Dict, Any, Tuple
from datetime import datetime as dt
import os
import logging

from FunPayAPI.types import LotShortcut

if TYPE_CHECKING:
    from cardinal import Cardinal
from FunPayAPI.updater.events import *
from tg_bot import CBT
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import telebot
from locales.localizer import Localizer
import tg_bot.static_keyboards

# Plugin metadata
NAME = "Steam Price Updater"
VERSION = "3.0.0"
DESCRIPTION = "Автоматическое обновление цен лотов на основе Steam API"
CREDITS = "@humblegodq"
UUID = "247153d9-f732-4f01-a11f-a3945b68b533"
SETTINGS_PAGE = True

# Setup logging
localizer = Localizer()
_ = localizer.translate
logger = logging.getLogger("FPC.steam_price_updater")
LOGGER_PREFIX = "[STEAM PRICE UPDATER]"

# Configuration
class Config:
    # Cache settings
    CACHE_TTL = 3600  # 1 hour
    
    # Processing settings
    CYCLE_PAUSE = 300  # 5 minutes
    LOT_PROCESSING_DELAY = 2  # 2 seconds between lots
    
    # API settings
    REQUEST_TIMEOUT = 15
    MAX_RETRIES = 2  # Reduced from 3
    
    # Supported currencies
    CURRENCIES = ["USD", "EUR", "RUB", "UAH", "KZT"]
    STEAM_CURRENCIES = ["USD", "EUR", "RUB", "UAH", "KZT"]

# Default settings
DEFAULT_SETTINGS = {
    "currency": "USD",
    "time": 21600,  # 6 hours
    "first_markup": 3.0,
    "second_markup": 5.0,
    "fixed_markup": 0.5,
    "max_price": 5000.0,
    "min_price": 1.0
}

# Global variables
SETTINGS = DEFAULT_SETTINGS.copy()
LOTS = {}
CARDINAL_INSTANCE = None
WIZARD_STATES = {}

# Single unified cache
class SimpleCache:
    """Простий потокобезпечний кеш з TTL"""
    
    def __init__(self, ttl: int = Config.CACHE_TTL):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["value"]
                else:
                    del self._cache[key]
            return None
    
    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = {
                "value": value,
                "timestamp": time.time()
            }
    
    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

# Single cache instance
cache = SimpleCache()

# Callback constants
CBT_MAIN_MENU = "SPU_main"
CBT_SETTINGS = "SPU_settings"
CBT_LOTS_MENU = "SPU_lots"
CBT_ADD_LOT = "SPU_add_lot"
CBT_EDIT_LOT = "SPU_edit_lot"
CBT_DELETE_LOT = "SPU_delete_lot"
CBT_TOGGLE_LOT = "SPU_toggle_lot"
CBT_UPDATE_NOW = "SPU_update_now"
CBT_STATS = "SPU_stats"
CBT_CHANGE_CURRENCY = "SPU_change_currency"
CBT_EDIT_SETTING = "SPU_edit_setting"

# === CORE FUNCTIONS ===

def get_currency_rate(target_currency: str = "USD") -> float:
    """Отримує курс валюти через єдиний API"""
    if target_currency == "USD":
        return 1.0
    
    cache_key = f"rate_{target_currency}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    try:
        # Single API source
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=Config.REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            rates = response.json().get("rates", {})
            rate = rates.get(target_currency, 1.0)
            cache.set(cache_key, rate)
            logger.info(f"{LOGGER_PREFIX} Updated rate USD/{target_currency}: {rate}")
            return rate
    
    except Exception as e:
        logger.warning(f"{LOGGER_PREFIX} Currency API error: {e}")
    
    # Fallback rates
    fallback_rates = {
        "UAH": 41.0,
        "RUB": 75.0,
        "KZT": 450.0,
        "EUR": 0.85
    }
    
    rate = fallback_rates.get(target_currency, 1.0)
    logger.warning(f"{LOGGER_PREFIX} Using fallback rate USD/{target_currency}: {rate}")
    return rate

def validate_steam_id(steam_id: str) -> Tuple[bool, str]:
    """Валідує Steam ID та повертає очищений ID"""
    if not steam_id or not str(steam_id).strip():
        return False, "Empty Steam ID"
    
    steam_id = str(steam_id).strip()
    
    # Sub ID format: sub_12345
    if steam_id.startswith("sub_"):
        sub_id = steam_id[4:]
        if sub_id.isdigit() and len(sub_id) > 0:
            return True, steam_id
        return False, "Invalid Sub ID format"
    
    # App ID format: 12345
    if steam_id.isdigit() and len(steam_id) > 0:
        return True, steam_id
    
    return False, "Invalid Steam ID format"

def get_steam_price(steam_id: str, currency: str = "USD") -> Optional[float]:
    """Отримує ціну з Steam API"""
    is_valid, clean_id = validate_steam_id(steam_id)
    if not is_valid:
        logger.warning(f"{LOGGER_PREFIX} Invalid Steam ID: {steam_id}")
        return None
    
    # Cache key
    cache_key = f"steam_{clean_id}_{currency}"
    cached_price = cache.get(cache_key)
    if cached_price is not None:
        return cached_price
    
    # Currency mapping
    currency_map = {
        "UAH": "ua",
        "KZT": "kz", 
        "RUB": "ru",
        "USD": "us",
        "EUR": "eu"
    }
    cc_code = currency_map.get(currency, "us")
    
    try:
        time.sleep(1)  # Simple rate limiting
        
        # Determine API endpoint
        is_sub = clean_id.startswith("sub_")
        if is_sub:
            package_id = clean_id[4:]
            url = f"https://store.steampowered.com/api/packagedetails/?packageids={package_id}&cc={cc_code}"
        else:
            url = f"https://store.steampowered.com/api/appdetails/?appids={clean_id}&cc={cc_code}&filters=price_overview"
        
        response = requests.get(url, timeout=Config.REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            item_id = package_id if is_sub else clean_id
            item_data = data.get(str(item_id), {})
            
            if item_data.get("success"):
                if is_sub:
                    price_data = item_data.get("data", {}).get("price")
                else:
                    price_data = item_data.get("data", {}).get("price_overview")
                
                if price_data:
                    final_price = price_data.get("final", 0)
                    if final_price > 0:
                        price_value = final_price / 100.0
                        cache.set(cache_key, price_value)
                        logger.debug(f"{LOGGER_PREFIX} Steam price for {clean_id}: {price_value} {currency}")
                        return price_value
        
        # Cache zero price to avoid repeated requests
        cache.set(cache_key, 0.0)
        return 0.0
        
    except Exception as e:
        logger.warning(f"{LOGGER_PREFIX} Steam API error for {clean_id}: {e}")
        return None

def calculate_lot_price(steam_price: float, steam_currency: str = "USD") -> float:
    """Розраховує ціну лота з наценками"""
    if steam_price <= 0:
        return SETTINGS["min_price"]
    
    try:
        account_currency = SETTINGS["currency"]
        
        # Convert to account currency
        if steam_currency == account_currency:
            base_price = steam_price
        else:
            if account_currency == "USD":
                # Convert from steam currency to USD
                if steam_currency == "USD":
                    base_price = steam_price
                else:
                    rate = get_currency_rate(steam_currency)
                    base_price = steam_price / rate if rate > 0 else steam_price
            else:
                # Convert steam -> USD -> account currency
                if steam_currency == "USD":
                    price_usd = steam_price
                else:
                    steam_rate = get_currency_rate(steam_currency)
                    price_usd = steam_price / steam_rate if steam_rate > 0 else steam_price
                
                account_rate = get_currency_rate(account_currency)
                base_price = price_usd * account_rate if account_rate > 0 else price_usd
        
        # Apply markups
        price_with_currency_markup = base_price * (1 + SETTINGS["first_markup"] / 100)
        final_price = price_with_currency_markup * (1 + SETTINGS["second_markup"] / 100) + SETTINGS["fixed_markup"]
        
        # Apply limits
        final_price = max(SETTINGS["min_price"], min(final_price, SETTINGS["max_price"]))
        
        return round(final_price, 2)
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Price calculation error: {e}")
        return SETTINGS["min_price"]

def update_lot_price(lot_id: str, lot_data: Dict, cardinal) -> bool:
    """Оновлює ціну одного лота"""
    try:
        steam_id = lot_data.get("steam_id")
        if not steam_id:
            logger.warning(f"{LOGGER_PREFIX} No Steam ID for lot {lot_id}")
            return False
        
        steam_currency = lot_data.get("steam_currency", "USD")
        
        # Get Steam price
        steam_price = get_steam_price(steam_id, steam_currency)
        if not steam_price or steam_price <= 0:
            logger.warning(f"{LOGGER_PREFIX} No Steam price for lot {lot_id}")
            return False
        
        # Calculate new price
        new_price = calculate_lot_price(steam_price, steam_currency)
        if new_price <= 0:
            return False
        
        # Apply lot limits
        lot_min = lot_data.get("min", SETTINGS["min_price"])
        lot_max = lot_data.get("max", SETTINGS["max_price"])
        new_price = max(lot_min, min(new_price, lot_max))
        
        # Update lot
        success = change_lot_price(cardinal, lot_id, new_price)
        if success:
            LOTS[lot_id]["last_steam_price"] = steam_price
            LOTS[lot_id]["last_price"] = new_price
            LOTS[lot_id]["last_update"] = time.time()
            logger.info(f"{LOGGER_PREFIX} Updated lot {lot_id}: {steam_price} {steam_currency} → ${new_price}")
        
        return success
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Error updating lot {lot_id}: {e}")
        return False

def change_lot_price(cardinal, lot_id: str, new_price: float) -> bool:
    """Змінює ціну лота через Cardinal API"""
    try:
        if lot_id not in LOTS:
            logger.warning(f"{LOGGER_PREFIX} Lot {lot_id} not found")
            return False
        
        # Get lot fields
        lot_fields = cardinal.account.get_lot_fields(int(lot_id))
        if not lot_fields or not hasattr(lot_fields, 'price'):
            logger.error(f"{LOGGER_PREFIX} Cannot get lot {lot_id} fields")
            # Remove invalid lot
            if lot_id in LOTS:
                del LOTS[lot_id]
                save_lots()
            return False
        
        old_price = lot_fields.price
        if old_price is None:
            return False
        
        # Update if price changed significantly
        if abs(new_price - old_price) >= 0.01:
            lot_fields.price = new_price
            cardinal.account.save_lot(lot_fields)
            logger.info(f"{LOGGER_PREFIX} Lot {lot_id}: {old_price:.2f} → {new_price:.2f}")
            return True
        else:
            logger.debug(f"{LOGGER_PREFIX} Lot {lot_id} price unchanged: {old_price:.2f}")
            return True
            
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Error changing lot {lot_id} price: {e}")
        if "не найден" in str(e).lower() or "not found" in str(e).lower():
            # Remove invalid lot
            if lot_id in LOTS:
                del LOTS[lot_id]
                save_lots()
        return False

def get_game_name(steam_id: str) -> str:
    """Отримує назву гри з Steam API"""
    cache_key = f"name_{steam_id}"
    cached_name = cache.get(cache_key)
    if cached_name:
        return cached_name
    
    try:
        is_sub = steam_id.startswith("sub_")
        if is_sub:
            package_id = steam_id[4:]
            url = f"https://store.steampowered.com/api/packagedetails?packageids={package_id}&filters=basic"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                package_data = data.get(str(package_id), {})
                if package_data.get("success"):
                    name = package_data.get("data", {}).get("name", f"Package {package_id}")
                    cache.set(cache_key, name)
                    return name
        else:
            url = f"https://store.steampowered.com/api/appdetails?appids={steam_id}&filters=basic"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                app_data = data.get(str(steam_id), {})
                if app_data.get("success"):
                    name = app_data.get("data", {}).get("name", f"App {steam_id}")
                    cache.set(cache_key, name)
                    return name
    except Exception as e:
        logger.debug(f"{LOGGER_PREFIX} Error getting game name for {steam_id}: {e}")
    
    return f"Steam {steam_id}"

# === FILE OPERATIONS ===

def save_settings():
    """Зберігає налаштування в файл"""
    try:
        os.makedirs("storage/plugins", exist_ok=True)
        with open("storage/plugins/steam_price_updater.json", "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, indent=2, ensure_ascii=False)
        logger.info(f"{LOGGER_PREFIX} Settings saved")
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Error saving settings: {e}")

def save_lots():
    """Зберігає лоти в файл"""
    try:
        os.makedirs("storage/plugins", exist_ok=True)
        with open("storage/plugins/steam_price_updater_lots.json", "w", encoding="utf-8") as f:
            json.dump(LOTS, f, indent=2, ensure_ascii=False)
        logger.info(f"{LOGGER_PREFIX} Lots saved: {len(LOTS)} lots")
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Error saving lots: {e}")

def load_settings():
    """Завантажує налаштування з файлу"""
    global SETTINGS
    try:
        if os.path.exists("storage/plugins/steam_price_updater.json"):
            with open("storage/plugins/steam_price_updater.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    loaded_settings = json.loads(content)
                    SETTINGS.update(loaded_settings)
                    logger.info(f"{LOGGER_PREFIX} Settings loaded")
    except Exception as e:
        logger.warning(f"{LOGGER_PREFIX} Error loading settings: {e}")

def load_lots():
    """Завантажує лоти з файлу"""
    global LOTS
    try:
        if os.path.exists("storage/plugins/steam_price_updater_lots.json"):
            with open("storage/plugins/steam_price_updater_lots.json", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    LOTS = json.loads(content)
                    
                    # Ensure all lots have required fields
                    for lot_id, lot_data in LOTS.items():
                        if "steam_id" not in lot_data:
                            lot_data["steam_id"] = str(lot_data.get("steam_app_id", "730"))
                        if "steam_currency" not in lot_data:
                            lot_data["steam_currency"] = "USD"
                        if "min" not in lot_data:
                            lot_data["min"] = SETTINGS["min_price"]
                        if "max" not in lot_data:
                            lot_data["max"] = SETTINGS["max_price"]
                        if "on" not in lot_data:
                            lot_data["on"] = True
                        if "last_update" not in lot_data:
                            lot_data["last_update"] = 0
                        if "last_price" not in lot_data:
                            lot_data["last_price"] = 0
                        if "last_steam_price" not in lot_data:
                            lot_data["last_steam_price"] = 0
                    
                    save_lots()  # Save cleaned data
                    logger.info(f"{LOGGER_PREFIX} Lots loaded: {len(LOTS)} lots")
    except Exception as e:
        logger.warning(f"{LOGGER_PREFIX} Error loading lots: {e}")
        LOTS = {}

# === TELEGRAM UI ===

def create_main_menu() -> Tuple[str, K]:
    """Створює головне меню"""
    active_lots = len([l for l in LOTS.values() if l.get("on", False)])
    total_lots = len(LOTS)
    
    text = f"🎮 <b>Steam Price Updater v{VERSION}</b>\n\n"
    text += f"📦 <b>Лоти:</b> {total_lots} всього, {active_lots} активних\n"
    text += f"⏱ <b>Інтервал:</b> {SETTINGS['time'] // 3600} год\n"
    text += f"💰 <b>Валюта:</b> {SETTINGS['currency']}\n\n"
    text += f"📈 <b>Наценки:</b> {SETTINGS['first_markup']}% + {SETTINGS['second_markup']}% + ${SETTINGS['fixed_markup']}"
    
    keyboard = K()
    keyboard.row(
        B("📦 Лоти", callback_data=f"{CBT_LOTS_MENU}:0"),
        B("⚙️ Налаштування", callback_data=CBT_SETTINGS)
    )
    keyboard.row(
        B("🔄 Оновити зараз", callback_data=CBT_UPDATE_NOW),
        B("📊 Статистика", callback_data=CBT_STATS)
    )
    keyboard.add(B("◀ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:0"))
    
    return text, keyboard

def create_lots_menu(page: int = 0) -> Tuple[str, K]:
    """Створює меню лотів"""
    per_page = 8
    lot_items = [(lot_id, lot_data) for lot_id, lot_data in LOTS.items()]
    total_lots = len(lot_items)
    
    # Sort by status (active first) then by ID
    lot_items.sort(key=lambda x: (not x[1].get("on", False), x[0]))
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_lots = lot_items[start_idx:end_idx]
    
    active_count = len([l for _, l in lot_items if l.get("on", False)])
    text = f"📦 <b>Управління лотами</b>\n\n"
    text += f"📊 <b>Всього:</b> {total_lots} | <b>Активних:</b> {active_count}\n"
    
    if total_lots > per_page:
        text += f"📄 <b>Сторінка:</b> {page + 1}/{(total_lots - 1) // per_page + 1}\n"
    text += "\n"
    
    keyboard = K()
    
    if total_lots == 0:
        text += "📝 <i>Лоти не додані</i>\n\n"
        text += "💡 Натисніть 'Додати лот' для початку роботи"
    else:
        text += "<b>Ваші лоти:</b>\n"
        for lot_id, lot_data in current_lots:
            game_name = get_game_name(lot_data.get("steam_id", ""))
            status_icon = "🟢" if lot_data.get("on", False) else "🔴"
            button_text = f"{status_icon} {game_name[:20]}"
            keyboard.add(B(button_text, callback_data=f"{CBT_EDIT_LOT}:{lot_id}"))
    
    # Navigation
    nav_buttons = []
    if page > 0:
        nav_buttons.append(B("⬅ Попер", callback_data=f"{CBT_LOTS_MENU}:{page-1}"))
    if end_idx < total_lots:
        nav_buttons.append(B("Наст ➡", callback_data=f"{CBT_LOTS_MENU}:{page+1}"))
    
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    # Action buttons
    keyboard.row(
        B("➕ Додати лот", callback_data=CBT_ADD_LOT),
        B("🔄 Оновити всі", callback_data=CBT_UPDATE_NOW)
    )
    keyboard.add(B("◀ Головне меню", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
    
    return text, keyboard

def create_edit_lot_menu(lot_id: str) -> Tuple[str, K]:
    """Створює меню редагування лота"""
    if lot_id not in LOTS:
        return "❌ Лот не знайдено", K()
    
    lot_data = LOTS[lot_id]
    game_name = get_game_name(lot_data.get("steam_id", ""))
    
    status_icon = "🟢" if lot_data.get("on", False) else "🔴"
    text = f"{status_icon} <b>Лот #{lot_id}</b>\n"
    text += f"🎮 <b>{game_name}</b>\n\n"
    
    # Steam info
    steam_id = lot_data.get("steam_id", "")
    steam_currency = lot_data.get("steam_currency", "USD")
    
    if steam_id.startswith("sub_"):
        text += f"📦 <b>Steam Sub ID:</b> {steam_id[4:]}\n"
        text += f"💿 <b>Тип:</b> DLC/Package\n"
    else:
        text += f"🎯 <b>Steam App ID:</b> {steam_id}\n"
        text += f"🎮 <b>Тип:</b> Гра\n"
    
    text += f"💱 <b>Валюта Steam:</b> {steam_currency}\n\n"
    
    # Price settings
    min_price = lot_data.get("min", SETTINGS["min_price"])
    max_price = lot_data.get("max", SETTINGS["max_price"])
    last_price = lot_data.get("last_price", 0)
    last_steam_price = lot_data.get("last_steam_price", 0)
    
    text += "💰 <b>Налаштування цін:</b>\n"
    text += f"🔻 Мін. ціна: ${min_price:.2f}\n"
    text += f"🔺 Макс. ціна: ${max_price:.2f}\n"
    
    if last_price > 0:
        text += f"💵 Поточна ціна: ${last_price:.2f}\n"
    if last_steam_price > 0:
        text += f"🎮 Steam ціна: {last_steam_price:.2f} {steam_currency}\n"
    
    # Last update
    last_update = lot_data.get("last_update", 0)
    if last_update > 0:
        last_update_str = dt.fromtimestamp(last_update).strftime("%d.%m %H:%M")
        text += f"\n📅 Останнє оновлення: {last_update_str}"
    else:
        text += f"\n📅 Останнє оновлення: Ніколи"
    
    keyboard = K()
    
    # Status toggle
    status_text = "❌ Вимкнути" if lot_data.get("on", False) else "✅ Увімкнути"
    keyboard.add(B(status_text, callback_data=f"{CBT_TOGGLE_LOT}:{lot_id}"))
    
    # Edit options
    keyboard.row(
        B("🔧 Steam ID", callback_data=f"{CBT_EDIT_SETTING}:lot:{lot_id}:steam_id"),
        B("💱 Валюта", callback_data=f"{CBT_EDIT_SETTING}:lot:{lot_id}:currency")
    )
    
    keyboard.row(
        B("💰 Мін. ціна", callback_data=f"{CBT_EDIT_SETTING}:lot:{lot_id}:min"),
        B("💸 Макс. ціна", callback_data=f"{CBT_EDIT_SETTING}:lot:{lot_id}:max")
    )
    
    # Actions
    keyboard.add(B("🔄 Оновити лот", callback_data=f"update_single:{lot_id}"))
    
    keyboard.row(
        B("🗑 Видалити", callback_data=f"{CBT_DELETE_LOT}:{lot_id}"),
        B("◀ До лотів", callback_data=f"{CBT_LOTS_MENU}:0")
    )
    
    return text, keyboard

# === SIMPLIFIED WIZARD ===

class SimpleWizard:
    """Простий wizard для додавання лотів"""
    
    def __init__(self):
        self.states = {}
    
    def start_add_lot(self, chat_id: int, user_id: int) -> Tuple[str, K]:
        """Початок додавання лота"""
        self.states[f"{chat_id}_{user_id}"] = {"step": "lot_id"}
        
        text = "🧙‍♂️ <b>Додавання нового лота</b>\n\n"
        text += "📋 <b>Крок 1: ID лота FunPay</b>\n\n"
        text += "Введіть ID лота з FunPay:\n"
        text += "• Знайдіть свій лот на funpay.com\n"
        text += "• Скопіюйте цифри з URL\n"
        text += "• Приклад: з URL funpay.com/lots/offer?id=<b>12345</b>\n"
        text += "• Введіть: <code>12345</code>"
        
        keyboard = K()
        keyboard.add(B("❌ Скасувати", callback_data=f"{CBT_LOTS_MENU}:0"))
        
        return text, keyboard
    
    def process_message(self, message, chat_id: int, user_id: int) -> Optional[Tuple[str, K]]:
        """Обробляє повідомлення wizard'а"""
        user_key = f"{chat_id}_{user_id}"
        if user_key not in self.states:
            return None
        
        state = self.states[user_key]
        step = state.get("step")
        text = message.text.strip()
        
        if step == "lot_id":
            return self._process_lot_id(text, user_key)
        elif step == "steam_id":
            return self._process_steam_id(text, user_key)
        elif step == "currency":
            return self._process_currency(text, user_key)
        elif step == "max_price":
            return self._process_max_price(text, user_key)
        
        return None
    
    def _process_lot_id(self, text: str, user_key: str) -> Tuple[str, K]:
        """Обробляє ID лота"""
        if not text.isdigit():
            return ("❌ ID лота повинен містити тільки цифри", K())
        
        if text in LOTS:
            return (f"❌ Лот {text} вже існує", K())
        
        self.states[user_key] = {"step": "steam_id", "lot_id": text}
        
        response_text = "🧙‍♂️ <b>Додавання нового лота</b>\n\n"
        response_text += "📋 <b>Крок 2: Steam ID гри</b>\n\n"
        response_text += f"✅ ID лота: <code>{text}</code>\n\n"
        response_text += "Введіть Steam ID гри:\n"
        response_text += "• Для звичайних ігор: <code>730</code> (CS2)\n"
        response_text += "• Для DLC/пакетів: <code>sub_12345</code>\n"
        response_text += "• Знайти можна на steamdb.info"
        
        keyboard = K()
        keyboard.add(B("❌ Скасувати", callback_data=f"{CBT_LOTS_MENU}:0"))
        
        return response_text, keyboard
    
    def _process_steam_id(self, text: str, user_key: str) -> Tuple[str, K]:
        """Обробляє Steam ID"""
        is_valid, clean_id = validate_steam_id(text)
        if not is_valid:
            return (f"❌ {clean_id}", K())
        
        # Test Steam API
        steam_price = get_steam_price(clean_id, "USD")
        if steam_price is None:
            return ("❌ Не вдалося отримати ціну з Steam API. Перевірте Steam ID", K())
        
        if steam_price == 0.0:
            return ("❌ Це безкоштовна гра. Неможливо створити лот", K())
        
        self.states[user_key].update({"step": "currency", "steam_id": clean_id})
        
        response_text = "🧙‍♂️ <b>Додавання нового лота</b>\n\n"
        response_text += "📋 <b>Крок 3: Валюта Steam</b>\n\n"
        response_text += f"✅ ID лота: <code>{self.states[user_key]['lot_id']}</code>\n"
        response_text += f"✅ Steam ID: <code>{clean_id}</code>\n\n"
        response_text += "Оберіть валюту для отримання цін Steam:"
        
        keyboard = K()
        keyboard.row(
            B("🇺🇦 UAH", callback_data=f"wizard_currency:{user_key}:UAH"),
            B("🇺🇸 USD", callback_data=f"wizard_currency:{user_key}:USD")
        )
        keyboard.row(
            B("🇷🇺 RUB", callback_data=f"wizard_currency:{user_key}:RUB"),
            B("🇰🇿 KZT", callback_data=f"wizard_currency:{user_key}:KZT")
        )
        keyboard.add(B("🇪🇺 EUR", callback_data=f"wizard_currency:{user_key}:EUR"))
        keyboard.add(B("❌ Скасувати", callback_data=f"{CBT_LOTS_MENU}:0"))
        
        return response_text, keyboard
    
    def select_currency(self, user_key: str, currency: str) -> Tuple[str, K]:
        """Вибір валюти"""
        if user_key not in self.states:
            return ("❌ Сесія завершена", K())
        
        # Calculate min price
        steam_id = self.states[user_key]["steam_id"]
        steam_price = get_steam_price(steam_id, currency)
        min_price = calculate_lot_price(steam_price, currency)
        
        self.states[user_key].update({
            "step": "max_price",
            "currency": currency,
            "min_price": min_price
        })
        
        response_text = "🧙‍♂️ <b>Додавання нового лота</b>\n\n"
        response_text += "📋 <b>Крок 4: Максимальна ціна</b>\n\n"
        response_text += f"✅ ID лота: <code>{self.states[user_key]['lot_id']}</code>\n"
        response_text += f"✅ Steam ID: <code>{steam_id}</code>\n"
        response_text += f"✅ Валюта: <code>{currency}</code>\n"
        response_text += f"✅ Мін. ціна: <code>${min_price:.2f}</code>\n\n"
        response_text += f"Введіть максимальну ціну (більше {min_price:.2f}):"
        
        keyboard = K()
        keyboard.add(B("❌ Скасувати", callback_data=f"{CBT_LOTS_MENU}:0"))
        
        return response_text, keyboard
    
    def _process_max_price(self, text: str, user_key: str) -> Tuple[str, K]:
        """Обробляє максимальну ціну"""
        try:
            max_price = float(text.replace(",", "."))
            min_price = self.states[user_key]["min_price"]
            
            if max_price <= min_price:
                return (f"❌ Максимальна ціна повинна бути більше {min_price:.2f}", K())
        except ValueError:
            return ("❌ Введіть коректну ціну (наприклад: 100.50)", K())
        
        # Create lot
        state = self.states[user_key]
        lot_id = state["lot_id"]
        
        LOTS[lot_id] = {
            "on": True,
            "steam_id": state["steam_id"],
            "steam_currency": state["currency"],
            "min": min_price,
            "max": max_price,
            "last_steam_price": 0,
            "last_price": 0,
            "last_update": 0
        }
        
        save_lots()
        
        # Clean up wizard state
        del self.states[user_key]
        
        response_text = "✅ <b>Лот успішно створено!</b>\n\n"
        response_text += f"📦 ID лота: <code>{lot_id}</code>\n"
        response_text += f"🎮 Steam ID: <code>{state['steam_id']}</code>\n"
        response_text += f"💰 Діапазон цін: ${min_price:.2f} - ${max_price:.2f}\n"
        response_text += f"🌍 Валюта Steam: {state['currency']}\n\n"
        response_text += f"⏰ Лот буде автоматично оновлюватися кожні {SETTINGS['time'] // 3600} год"
        
        keyboard = K()
        keyboard.row(
            B("📦 До лотів", callback_data=f"{CBT_LOTS_MENU}:0"),
            B("🔄 Оновити зараз", callback_data=f"update_single:{lot_id}")
        )
        
        return response_text, keyboard
    
    def clear_state(self, chat_id: int, user_id: int):
        """Очищає стан wizard'а"""
        user_key = f"{chat_id}_{user_id}"
        if user_key in self.states:
            del self.states[user_key]

# Global wizard instance
wizard = SimpleWizard()

# === TELEGRAM HANDLERS ===

def init(cardinal: Cardinal):
    """Ініціалізація плагіна"""
    global CARDINAL_INSTANCE
    CARDINAL_INSTANCE = cardinal
    
    if not cardinal.telegram:
        logger.warning(f"{LOGGER_PREFIX} Telegram bot not enabled")
        return
    
    # Load data
    load_settings()
    load_lots()
    
    tg = cardinal.telegram
    bot = tg.bot
    
    logger.info(f"{LOGGER_PREFIX} Initializing Telegram handlers...")
    
    # === MAIN HANDLERS ===
    
    def show_main_menu(call: telebot.types.CallbackQuery):
        """Показує головне меню"""
        try:
            text, keyboard = create_main_menu()
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in show_main_menu: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_lots_menu(call: telebot.types.CallbackQuery):
        """Показує меню лотів"""
        try:
            page = int(call.data.split(":")[-1]) if call.data.split(":")[-1].isdigit() else 0
            text, keyboard = create_lots_menu(page)
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in show_lots_menu: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_settings(call: telebot.types.CallbackQuery):
        """Показує налаштування"""
        try:
            text = f"⚙️ <b>Налаштування Steam Price Updater</b>\n\n"
            text += f"💱 <b>Валюта:</b> {SETTINGS['currency']}\n"
            text += f"⏱ <b>Інтервал:</b> {SETTINGS['time'] // 3600} год\n\n"
            text += f"<b>💰 Наценки:</b>\n"
            text += f"📈 На курс: {SETTINGS['first_markup']}%\n"
            text += f"📊 Маржа: {SETTINGS['second_markup']}%\n"
            text += f"💵 Фіксована: ${SETTINGS['fixed_markup']}\n\n"
            text += f"<b>🔧 Ліміти:</b>\n"
            text += f"🔻 Мін. ціна: ${SETTINGS['min_price']}\n"
            text += f"🔺 Макс. ціна: ${SETTINGS['max_price']}"
            
            keyboard = K()
            keyboard.row(
                B("💱 Валюта", callback_data=CBT_CHANGE_CURRENCY),
                B("⏱ Інтервал", callback_data=f"{CBT_EDIT_SETTING}:time")
            )
            keyboard.row(
                B("📈 Наценка курсу", callback_data=f"{CBT_EDIT_SETTING}:first_markup"),
                B("📊 Маржа", callback_data=f"{CBT_EDIT_SETTING}:second_markup")
            )
            keyboard.row(
                B("💵 Фікс. наценка", callback_data=f"{CBT_EDIT_SETTING}:fixed_markup"),
                B("🔧 Ліміти цін", callback_data=f"{CBT_EDIT_SETTING}:limits")
            )
            keyboard.add(B("◀ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in show_settings: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def start_add_lot_wizard(call: telebot.types.CallbackQuery):
        """Запускає wizard додавання лота"""
        try:
            text, keyboard = wizard.start_add_lot(call.message.chat.id, call.from_user.id)
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id, "🧙‍♂️ Починаємо додавання лота")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in start_add_lot_wizard: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_edit_lot(call: telebot.types.CallbackQuery):
        """Показує меню редагування лота"""
        try:
            lot_id = call.data.split(":")[-1]
            text, keyboard = create_edit_lot_menu(lot_id)
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in show_edit_lot: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def toggle_lot(call: telebot.types.CallbackQuery):
        """Перемикає статус лота"""
        try:
            lot_id = call.data.split(":")[-1]
            if lot_id in LOTS:
                LOTS[lot_id]["on"] = not LOTS[lot_id].get("on", False)
                save_lots()
                status = "увімкнений" if LOTS[lot_id]["on"] else "вимкнений"
                bot.answer_callback_query(call.id, f"Лот {status}")
                show_edit_lot(call)
            else:
                bot.answer_callback_query(call.id, "❌ Лот не знайдено")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in toggle_lot: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def delete_lot(call: telebot.types.CallbackQuery):
        """Видаляє лот"""
        try:
            lot_id = call.data.split(":")[-1]
            if lot_id in LOTS:
                del LOTS[lot_id]
                save_lots()
                bot.answer_callback_query(call.id, f"Лот {lot_id} видалено")
                show_lots_menu(call)
            else:
                bot.answer_callback_query(call.id, "❌ Лот не знайдено")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in delete_lot: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def change_currency(call: telebot.types.CallbackQuery):
        """Змінює валюту аккаунта"""
        try:
            current_currency = SETTINGS["currency"]
            currencies = Config.CURRENCIES
            try:
                current_index = currencies.index(current_currency)
                SETTINGS["currency"] = currencies[(current_index + 1) % len(currencies)]
            except ValueError:
                SETTINGS["currency"] = "USD"
            
            save_settings()
            
            currency_symbols = {"USD": "$", "RUB": "₽", "EUR": "€"}
            symbol = currency_symbols.get(SETTINGS["currency"], SETTINGS["currency"])
            bot.answer_callback_query(call.id, f"Валюта: {symbol} {SETTINGS['currency']}")
            
            show_settings(call)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in change_currency: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def update_all_lots(call: telebot.types.CallbackQuery):
        """Оновлює всі активні лоти"""
        try:
            if not CARDINAL_INSTANCE:
                bot.answer_callback_query(call.id, "❌ Cardinal недоступний")
                return
            
            active_lots = [lot_id for lot_id, lot_data in LOTS.items() 
                          if lot_data.get("on", False)]
            
            if not active_lots:
                bot.answer_callback_query(call.id, "Немає активних лотів")
                return
            
            bot.answer_callback_query(call.id, "Оновлення розпочато...")
            
            def update_thread():
                updated = 0
                failed = 0
                
                for lot_id in active_lots:
                    try:
                        lot_data = LOTS[lot_id]
                        if update_lot_price(lot_id, lot_data, CARDINAL_INSTANCE):
                            updated += 1
                        else:
                            failed += 1
                        time.sleep(Config.LOT_PROCESSING_DELAY)
                    except Exception as e:
                        logger.error(f"{LOGGER_PREFIX} Error updating lot {lot_id}: {e}")
                        failed += 1
                
                save_lots()
                result_text = f"✅ Оновлення завершено!\n📈 Оновлено: {updated}\n❌ Помилок: {failed}"
                bot.send_message(call.message.chat.id, result_text)
            
            Thread(target=update_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in update_all_lots: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def update_single_lot(call: telebot.types.CallbackQuery):
        """Оновлює один лот"""
        try:
            lot_id = call.data.split(":")[-1]
            
            if lot_id not in LOTS:
                bot.answer_callback_query(call.id, "❌ Лот не знайдено")
                return
            
            if not LOTS[lot_id].get("on", False):
                bot.answer_callback_query(call.id, "❌ Лот вимкнений")
                return
            
            bot.answer_callback_query(call.id, f"🔄 Оновлюю лот {lot_id}...")
            
            def update_thread():
                try:
                    lot_data = LOTS[lot_id]
                    success = update_lot_price(lot_id, lot_data, CARDINAL_INSTANCE)
                    
                    if success:
                        save_lots()
                        bot.send_message(call.message.chat.id, f"✅ Лот {lot_id} оновлено!")
                    else:
                        bot.send_message(call.message.chat.id, f"❌ Помилка оновлення лота {lot_id}")
                        
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Error updating single lot: {e}")
                    bot.send_message(call.message.chat.id, f"❌ Помилка: {e}")
            
            Thread(target=update_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in update_single_lot: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def show_stats(call: telebot.types.CallbackQuery):
        """Показує статистику"""
        try:
            active_lots = len([l for l in LOTS.values() if l.get("on", False)])
            lots_with_prices = len([l for l in LOTS.values() if l.get("last_price", 0) > 0])
            
            text = f"📊 <b>Статистика Steam Price Updater</b>\n\n"
            text += f"📦 Всього лотів: {len(LOTS)}\n"
            text += f"✅ Активних: {active_lots}\n"
            text += f"💰 З цінами: {lots_with_prices}\n\n"
            
            # Currency rates
            try:
                text += f"<b>💱 Курси валют (USD до місцевої):</b>\n"
                for currency in ["UAH", "RUB", "EUR"]:
                    rate = get_currency_rate(currency)
                    text += f"• {currency}: {rate:.2f}\n"
            except:
                text += f"💱 Курси валют: завантаження...\n"
            
            # Last update
            if LOTS:
                recent_updates = [lot.get("last_update", 0) for lot in LOTS.values() if lot.get("last_update", 0) > 0]
                if recent_updates:
                    last_update = max(recent_updates)
                    last_update_str = dt.fromtimestamp(last_update).strftime("%d.%m %H:%M")
                    text += f"\n🕐 Останнє оновлення: {last_update_str}"
                else:
                    text += f"\n🕐 Останнє оновлення: Ніколи"
            
            keyboard = K()
            keyboard.add(B("🔄 Оновити курси", callback_data="refresh_rates"))
            keyboard.add(B("◀ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in show_stats: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def refresh_rates(call: telebot.types.CallbackQuery):
        """Оновлює курси валют"""
        try:
            bot.answer_callback_query(call.id, "Оновлюю курси...")
            
            def refresh_thread():
                try:
                    cache.clear()
                    
                    rates_text = "💱 <b>Курси валют оновлено:</b>\n\n"
                    for currency in ["UAH", "RUB", "EUR"]:
                        rate = get_currency_rate(currency)
                        rates_text += f"• USD/{currency}: {rate:.2f}\n"
                    
                    rates_text += f"\n🕐 {time.strftime('%H:%M:%S')}"
                    bot.send_message(call.message.chat.id, rates_text, parse_mode="HTML")
                    
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Error refreshing rates: {e}")
                    bot.send_message(call.message.chat.id, "❌ Помилка оновлення курсів")
            
            Thread(target=refresh_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in refresh_rates: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def handle_wizard_currency(call: telebot.types.CallbackQuery):
        """Обробляє вибір валюти в wizard'і"""
        try:
            parts = call.data.split(":")
            user_key = parts[1]
            currency = parts[2]
            
            text, keyboard = wizard.select_currency(user_key, currency)
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id, f"✅ Валюта: {currency}")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in handle_wizard_currency: {e}")
            bot.answer_callback_query(call.id, "❌ Помилка")
    
    def handle_wizard_message(message: telebot.types.Message):
        """Обробляє повідомлення wizard'а"""
        try:
            if not message.text or not message.from_user:
                return
            
            result = wizard.process_message(message, message.chat.id, message.from_user.id)
            if result:
                text, keyboard = result
                bot.send_message(message.chat.id, text, reply_markup=keyboard, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Error in handle_wizard_message: {e}")
            wizard.clear_state(message.chat.id, message.from_user.id)
            bot.reply_to(message, "❌ Сталася помилка")
    
    # Register handlers
    tg.cbq_handler(show_main_menu, lambda c: c.data and c.data.startswith(f"{CBT.PLUGIN_SETTINGS}:{UUID}"))
    tg.cbq_handler(show_lots_menu, lambda c: c.data and c.data.startswith(CBT_LOTS_MENU))
    tg.cbq_handler(show_settings, lambda c: c.data and c.data == CBT_SETTINGS)
    tg.cbq_handler(start_add_lot_wizard, lambda c: c.data and c.data == CBT_ADD_LOT)
    tg.cbq_handler(show_edit_lot, lambda c: c.data and c.data.startswith(CBT_EDIT_LOT))
    tg.cbq_handler(toggle_lot, lambda c: c.data and c.data.startswith(CBT_TOGGLE_LOT))
    tg.cbq_handler(delete_lot, lambda c: c.data and c.data.startswith(CBT_DELETE_LOT))
    tg.cbq_handler(change_currency, lambda c: c.data and c.data == CBT_CHANGE_CURRENCY)
    tg.cbq_handler(update_all_lots, lambda c: c.data and c.data == CBT_UPDATE_NOW)
    tg.cbq_handler(update_single_lot, lambda c: c.data and c.data.startswith("update_single:"))
    tg.cbq_handler(show_stats, lambda c: c.data and c.data == CBT_STATS)
    tg.cbq_handler(refresh_rates, lambda c: c.data and c.data == "refresh_rates")
    tg.cbq_handler(handle_wizard_currency, lambda c: c.data and c.data.startswith("wizard_currency:"))
    
    # Message handler for wizard
    tg.msg_handler(handle_wizard_message)
    
    logger.info(f"{LOGGER_PREFIX} Initialization completed")

def post_start(cardinal):
    """Запускає основний цикл обновлення"""
    
    def main_loop():
        """Основний цикл обробки лотів"""
        global LOTS, CARDINAL_INSTANCE
        lot_last_check = {}
        
        logger.info(f"{LOGGER_PREFIX} Main processing loop started")
        
        while True:
            try:
                current_time = time.time()
                
                for lot_id, lot_data in LOTS.items():
                    if not lot_data.get("on", False):
                        continue
                    
                    # Check if it's time to update this lot
                    last_check = lot_last_check.get(lot_id, 0)
                    if current_time - last_check < SETTINGS["time"]:
                        continue
                    
                    lot_last_check[lot_id] = current_time
                    
                    logger.info(f"{LOGGER_PREFIX} Processing lot {lot_id}")
                    
                    try:
                        update_lot_price(lot_id, lot_data, CARDINAL_INSTANCE)
                        time.sleep(Config.LOT_PROCESSING_DELAY)
                    except Exception as e:
                        logger.error(f"{LOGGER_PREFIX} Error processing lot {lot_id}: {e}")
                
                # Save lots after processing
                save_lots()
                
            except Exception as e:
                logger.error(f"{LOGGER_PREFIX} Critical error in main loop: {e}")
            
            time.sleep(Config.CYCLE_PAUSE)
    
    # Start main loop thread
    if not hasattr(cardinal, '_steam_updater_running'):
        logger.info(f"{LOGGER_PREFIX} Starting main processing thread")
        thread = Thread(target=main_loop, daemon=True)
        thread.start()
        cardinal._steam_updater_running = True
    else:
        logger.info(f"{LOGGER_PREFIX} Main thread already running")

# Plugin bindings
BIND_TO_PRE_INIT = [init]
BIND_TO_POST_START = [post_start]
BIND_TO_DELETE = None