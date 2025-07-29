"""
Модуль для работы с Steam API
"""

import time
import requests
import logging
from typing import Optional, Tuple

from ..core.config import Config, LOGGER_PREFIX, settings_manager
from ..core.cache import cache_manager

logger = logging.getLogger("FPC.steam_price_updater")

class SteamAPI:
    """API для работы со Steam Store"""
    
    # Карта валют для Steam API
    CURRENCY_MAP = {
        "UAH": "ua",
        "KZT": "kz", 
        "RUB": "ru",
        "USD": "us",
        "EUR": "eu"
    }
    
    def validate_steam_id(self, steam_id: str) -> Tuple[bool, str, str]:
        """
        Валидирует Steam ID
        Возвращает: (is_valid, id_type, clean_id)
        """
        if not steam_id or not str(steam_id).strip():
            return False, "", ""
        
        steam_id = str(steam_id).strip()
        
        # Проверяем Sub ID
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
            # Проверяем App ID
            if steam_id.isdigit() and len(steam_id) > 0:
                return True, "app", steam_id
            else:
                return False, "", ""
    
    def get_steam_price(self, steam_id: str, currency_code: str = "UAH") -> Optional[float]:
        """
        Получает цену игры/DLC из Steam Store API
        """
        # Валидируем Steam ID
        is_valid, id_type, clean_id = self.validate_steam_id(steam_id)
        if not is_valid:
            logger.warning(f"{LOGGER_PREFIX} Неверный формат Steam ID: {steam_id}")
            return None
        
        # Получаем код страны для API
        cc_code = self.CURRENCY_MAP.get(currency_code, "ua")
        
        # Проверяем кеш
        cached_price = cache_manager.get_steam_price(steam_id, currency_code)
        if cached_price is not None:
            logger.debug(f"{LOGGER_PREFIX} Кешированная цена для Steam {steam_id} ({currency_code})")
            return cached_price
        
        # Получаем цену из API
        price = self._fetch_price_from_api(id_type, clean_id, cc_code)
        
        if price is not None:
            # Кешируем результат
            cache_manager.set_steam_price(steam_id, currency_code, price)
            logger.debug(f"{LOGGER_PREFIX} Steam цена для {steam_id}: {price} {currency_code}")
        
        return price
    
    def _fetch_price_from_api(self, id_type: str, clean_id: str, cc_code: str) -> Optional[float]:
        """Получает цену из Steam API"""
        try:
            # Задержка между запросами
            time.sleep(settings_manager.get("steam_request_delay", Config.STEAM_REQUEST_DELAY))
            
            if id_type == "sub":
                return self._fetch_package_price(clean_id, cc_code)
            else:
                return self._fetch_app_price(clean_id, cc_code)
                
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка получения Steam цены для {clean_id} ({cc_code}): {e}")
            return None
    
    def _fetch_package_price(self, package_id: str, cc_code: str) -> Optional[float]:
        """Получает цену пакета (Sub ID)"""
        url = f"https://store.steampowered.com/api/packagedetails/?packageids={package_id}&cc={cc_code}"
        response = requests.get(url, timeout=settings_manager.get("request_timeout", Config.REQUEST_TIMEOUT))
        
        if response.status_code == 200:
            data = response.json()
            package_data = data.get(str(package_id))
            
            if package_data and package_data.get("success"):
                price_overview = package_data.get("data", {}).get("price")
                
                if price_overview:
                    final_price = price_overview.get("final", 0)
                    if final_price > 0:
                        return final_price / 100.0
                
                # Бесплатный контент
                return 0.0
        
        return None
    
    def _fetch_app_price(self, app_id: str, cc_code: str) -> Optional[float]:
        """Получает цену приложения (App ID)"""
        url = f"https://store.steampowered.com/api/appdetails/?appids={app_id}&cc={cc_code}&filters=price_overview"
        response = requests.get(url, timeout=settings_manager.get("request_timeout", Config.REQUEST_TIMEOUT))
        
        if response.status_code == 200:
            data = response.json()
            app_data = data.get(str(app_id))
            
            if app_data and app_data.get("success"):
                price_overview = app_data.get("data", {}).get("price_overview")
                
                if price_overview:
                    final_price = price_overview.get("final", 0)
                    if final_price > 0:
                        return final_price / 100.0
                
                # Бесплатная игра
                return 0.0
        
        return None
    
    def get_game_name(self, steam_id: str) -> str:
        """Получает название игры из Steam API"""
        if not steam_id:
            return "Неизвестная игра"
        
        # Проверяем кеш
        cached_name = cache_manager.get_game_name(steam_id)
        if cached_name:
            return cached_name
        
        # Получаем название из API
        name = self._fetch_game_name_from_api(steam_id)
        
        if name:
            cache_manager.set_game_name(steam_id, name)
            return name
        
        return f"Steam {steam_id}"
    
    def _fetch_game_name_from_api(self, steam_id: str) -> Optional[str]:
        """Получает название игры из Steam API"""
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
            logger.debug(f"{LOGGER_PREFIX} Ошибка получения названия игры {steam_id}: {e}")
        
        return None

# Глобальный экземпляр API
steam_api = SteamAPI()