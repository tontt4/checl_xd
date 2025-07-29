"""
Модуль конфігурації для Steam Price Updater
"""

import json
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("FPC.steam_price_updater")

# Константы плагина
NAME = "Steam Price Updater"
VERSION = "2.1.0"
DESCRIPTION = "Автоматическое обновление цен лотов на основе Steam API с выбором валют"
CREDITS = "@humblegodq"
UUID = "247153d9-f732-4f01-a11f-a3945b68b533"
SETTINGS_PAGE = True

LOGGER_PREFIX = "[STEAM PRICE UPDATER]"

class Config:
    """Конфигурация плагина"""
    # Кеширование
    CACHE_TTL = 3600  # 1 час
    
    # Циклы и задержки
    CYCLE_PAUSE = 300  # 5 минут
    LOT_PROCESSING_DELAY = 2  # 2 секунды между лотами
    
    # Пагинация
    LOTS_PER_PAGE = 8
    
    # Steam API
    STEAM_REQUEST_DELAY = 10  # 10 секунд между запросами
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 15
    
    # Валюты
    DEFAULT_STEAM_CURRENCY = "UAH"
    SUPPORTED_CURRENCIES = ["UAH", "KZT", "RUB", "USD", "EUR"]
    ACCOUNT_CURRENCIES = ["USD", "RUB", "EUR"]
    
    # Кеш
    MAX_CACHE_SIZE = 1000

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    "currency": "USD",
    "account_currency": "USD", 
    "time": 21600,  # 6 часов
    "first_markup": 3.0,  # Наценка на валютный курс
    "second_markup": 5.0,  # Маржа прибыли
    "fixed_markup": 0.5,  # Фиксированная наценка
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

class SettingsManager:
    """Менеджер настроек"""
    
    def __init__(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.settings_file = "storage/plugins/steam_price_updater.json"
    
    def load_settings(self):
        """Загружает настройки из файла"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        loaded_settings = json.loads(content)
                        self.settings.update(loaded_settings)
                        logger.info(f"{LOGGER_PREFIX} Настройки загружены")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка загрузки настроек: {e}")
    
    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            os.makedirs("storage/plugins", exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.settings, indent=4, ensure_ascii=False))
            logger.info(f"{LOGGER_PREFIX} Настройки сохранены")
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка сохранения настроек: {e}")
    
    def get(self, key: str, default=None):
        """Получает значение настройки"""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """Устанавливает значение настройки"""
        self.settings[key] = value
    
    def update(self, new_settings: Dict[str, Any]):
        """Обновляет настройки"""
        self.settings.update(new_settings)

# Глобальный экземпляр настроек
settings_manager = SettingsManager()