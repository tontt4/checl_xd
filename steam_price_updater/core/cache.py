"""
Модуль кешування для Steam Price Updater
"""

import time
import logging
from threading import Lock
from typing import Optional, Dict, Any

from .config import Config, LOGGER_PREFIX

logger = logging.getLogger("FPC.steam_price_updater")

class UnifiedCache:
    """Единая система кеширования"""
    
    def __init__(self, max_size: int = Config.MAX_CACHE_SIZE, ttl: int = Config.CACHE_TTL):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        """Получает значение из кеша с проверкой TTL"""
        with self._lock:
            if key in self.cache:
                entry = self.cache[key]
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["value"]
                else:
                    # Удаляем устаревшую запись
                    try:
                        del self.cache[key]
                    except KeyError:
                        pass
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение в кеш"""
        with self._lock:
            # Очищаем место если кеш переполнен
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
        """Проверяет наличие ключа в кеше"""
        return self.get(key) is not None
    
    def clear(self) -> None:
        """Очищает весь кеш"""
        with self._lock:
            self.cache.clear()
    
    def clear_expired(self) -> int:
        """Очищает устаревшие записи"""
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
        """Возвращает размер кеша"""
        with self._lock:
            return len(self.cache)
    
    def clear_pattern(self, pattern: str) -> int:
        """Очищает записи по паттерну"""
        with self._lock:
            matching_keys = [k for k in self.cache.keys() if pattern in k]
            for key in matching_keys:
                try:
                    del self.cache[key]
                except KeyError:
                    pass
            return len(matching_keys)

class CacheManager:
    """Менеджер кеша с специализированными методами"""
    
    def __init__(self):
        self.cache = UnifiedCache()
    
    def get_steam_price(self, steam_id: str, currency: str) -> Optional[float]:
        """Получает цену Steam из кеша"""
        key = f"steam_price_{steam_id}_{currency}"
        cached_data = self.cache.get(key)
        if cached_data and isinstance(cached_data, dict):
            return cached_data.get("price")
        return None
    
    def set_steam_price(self, steam_id: str, currency: str, price: float) -> None:
        """Сохраняет цену Steam в кеш"""
        key = f"steam_price_{steam_id}_{currency}"
        self.cache.set(key, {"price": price})
        logger.debug(f"{LOGGER_PREFIX} Цена Steam кеширована: {steam_id} = {price} {currency}")
    
    def get_currency_rate(self, currency: str) -> Optional[Dict[str, Any]]:
        """Получает курс валюты из кеша"""
        key = f"currency_rate_{currency}"
        return self.cache.get(key)
    
    def set_currency_rate(self, currency: str, rate: float, source: str = "unknown") -> None:
        """Сохраняет курс валюты в кеш"""
        key = f"currency_rate_{currency}"
        data = {
            "rate": rate,
            "timestamp": time.time(),
            "source": source
        }
        self.cache.set(key, data)
        logger.debug(f"{LOGGER_PREFIX} Курс валюты кеширован: USD/{currency} = {rate} ({source})")
    
    def get_game_name(self, steam_id: str) -> Optional[str]:
        """Получает название игры из кеша"""
        key = f"game_name_{steam_id}"
        cached_data = self.cache.get(key)
        if cached_data and isinstance(cached_data, dict):
            return cached_data.get("name")
        return None
    
    def set_game_name(self, steam_id: str, name: str) -> None:
        """Сохраняет название игры в кеш"""
        key = f"game_name_{steam_id}"
        self.cache.set(key, {"name": name})
    
    def clear_currency_cache(self) -> int:
        """Очищает кеш курсов валют"""
        return self.cache.clear_pattern("currency_rate_")
    
    def clear_steam_cache(self) -> int:
        """Очищает кеш цен Steam"""
        return self.cache.clear_pattern("steam_price_")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Возвращает статистику кеша"""
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

# Глобальный экземпляр кеша
cache_manager = CacheManager()