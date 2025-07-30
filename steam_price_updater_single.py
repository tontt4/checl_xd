"""
Steam Price Updater Plugin - Об'єднана версія у одному файлі
Автоматическое обновление цен лотов на основе Steam API с выбором валют

Версия: 2.1.0 (combined)
Автор: @humblegodq
UUID: 247153d9-f732-4f01-a11f-a3945b68b533
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

# Настройка логирования
logger = logging.getLogger("FPC.steam_price_updater")

# ===== КОНСТАНТЫ И КОНФИГУРАЦИЯ =====

NAME = "Steam Price Updater"
VERSION = "2.1.0"
DESCRIPTION = "Автоматическое обновление цен лотов на основе Steam API с выбором валют"
CREDITS = "@humblegodq"
UUID = "247153d9-f732-4f01-a11f-a3945b68b533"
SETTINGS_PAGE = True
LOGGER_PREFIX = "[STEAM PRICE UPDATER]"

class Config:
    """Конфигурация плагина"""
    CACHE_TTL = 3600  # 1 час
    CYCLE_PAUSE = 300  # 5 минут
    LOT_PROCESSING_DELAY = 2  # 2 секунды между лотами
    LOTS_PER_PAGE = 8
    STEAM_REQUEST_DELAY = 10  # 10 секунд между запросами
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 15
    DEFAULT_STEAM_CURRENCY = "UAH"
    SUPPORTED_CURRENCIES = ["UAH", "KZT", "RUB", "USD", "EUR"]
    ACCOUNT_CURRENCIES = ["USD", "RUB", "EUR"]
    MAX_CACHE_SIZE = 1000

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
