"""
Steam Price Updater Plugin - Рефакторована версія

Автоматическое обновление цен лотов на основе Steam API с выбором валют

Версия: 2.1.0 (рефакторинг)
Автор: @humblegodq
UUID: 247153d9-f732-4f01-a11f-a3945b68b533
"""

from __future__ import annotations
import atexit
import logging
from typing import TYPE_CHECKING

# Импорты рефакторированных модулей
from steam_price_updater.core.config import (
    NAME, VERSION, DESCRIPTION, CREDITS, UUID, SETTINGS_PAGE, 
    LOGGER_PREFIX, settings_manager
)
from steam_price_updater.core.lot_manager import lot_manager
from steam_price_updater.core.updater import lot_updater
from steam_price_updater.core.cache import cache_manager
from steam_price_updater.ui.telegram_handlers import telegram_handlers

if TYPE_CHECKING:
    from cardinal import Cardinal

# Настройка логирования
logger = logging.getLogger("FPC.steam_price_updater")

def cleanup_resources():
    """Очистка ресурсов при завершении"""
    try:
        logger.info(f"{LOGGER_PREFIX} Очистка ресурсов...")
        
        # Останавливаем обработчик
        lot_updater.stop()
        
        # Сохраняем данные
        lot_manager.save_lots()
        settings_manager.save_settings()
        
        # Очищаем кеш
        cache_manager.cache.clear_expired()
        
        logger.info(f"{LOGGER_PREFIX} Ресурсы очищены")
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Ошибка очистки ресурсов: {e}")

def check_cardinal_health(cardinal) -> bool:
    """Проверяет доступность Cardinal"""
    try:
        return hasattr(cardinal, 'account') and cardinal.account is not None
    except Exception:
        return False

def init(cardinal: Cardinal):
    """Инициализация плагина"""
    try:
        logger.info(f"{LOGGER_PREFIX} Инициализация Steam Price Updater v{VERSION}")
        
        # Проверяем здоровье Cardinal
        if not check_cardinal_health(cardinal):
            logger.error(f"{LOGGER_PREFIX} Cardinal недоступен")
            return
        
        # Регистрируем очистку ресурсов
        atexit.register(cleanup_resources)
        
        # Загружаем настройки и лоты
        settings_manager.load_settings()
        lot_manager.load_lots()
        
        # Настраиваем Telegram обработчики
        telegram_handlers.setup(cardinal)
        
        logger.info(f"{LOGGER_PREFIX} Инициализация завершена успешно")
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Критическая ошибка инициализации: {e}")
        raise

def post_start(cardinal: Cardinal):
    """Запуск плагина после старта Cardinal"""
    try:
        logger.info(f"{LOGGER_PREFIX} Запуск плагина...")
        
        # Проверяем здоровье Cardinal
        if not check_cardinal_health(cardinal):
            logger.error(f"{LOGGER_PREFIX} Cardinal недоступен при запуске")
            return
        
        # Запускаем основной цикл обработки
        lot_updater.start(cardinal)
        
        # Логируем статистику
        stats = lot_manager.get_lots_stats()
        logger.info(f"{LOGGER_PREFIX} Плагин запущен. Лотов: {stats['total']}, активных: {stats['active']}")
        
    except Exception as e:
        logger.error(f"{LOGGER_PREFIX} Ошибка запуска плагина: {e}")

def validate_plugin_integrity():
    """Проверяет целостность плагина"""
    required_components = [
        settings_manager,
        lot_manager, 
        lot_updater,
        cache_manager,
        telegram_handlers
    ]
    
    for component in required_components:
        if component is None:
            logger.error(f"{LOGGER_PREFIX} Отсутствует компонент: {component}")
            return False
    
    return True

# Валидация целостности при импорте
try:
    if not validate_plugin_integrity():
        raise ImportError("Не удалось проверить целостность плагина")
    
    logger.info(f"{LOGGER_PREFIX} Плагин загружен и проверен")
    
except Exception as e:
    logger.error(f"{LOGGER_PREFIX} Критическая ошибка загрузки плагина: {e}")
    raise

# Привязка функций к событиям Cardinal
BIND_TO_PRE_INIT = [init]
BIND_TO_POST_START = [post_start]
BIND_TO_DELETE = [cleanup_resources]