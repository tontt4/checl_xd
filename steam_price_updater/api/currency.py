"""
Модуль для работы с курсами валют
"""

import time
import requests
import logging
from typing import Optional

from ..core.config import Config, LOGGER_PREFIX
from ..core.cache import cache_manager

logger = logging.getLogger("FPC.steam_price_updater")

class CurrencyAPI:
    """API для получения курсов валют"""
    
    # Фиксированные курсы как fallback
    FALLBACK_RATES = {
        "UAH": 41.82,
        "RUB": 78.42,
        "KZT": 519.86,
        "EUR": 0.85,
        "USD": 1.0
    }
    
    def get_currency_rate(self, currency: str) -> float:
        """Получает курс валюты USD к указанной валюте"""
        currency = currency.upper()
        
        # Проверяем кеш
        cached_rate = cache_manager.get_currency_rate(currency)
        if cached_rate:
            cache_age = time.time() - cached_rate.get("timestamp", 0)
            if cache_age < 900:  # 15 минут
                logger.debug(f"{LOGGER_PREFIX} Использую кеш для USD/{currency}: {cached_rate.get('rate')}")
                return cached_rate.get("rate", self._get_fallback_rate(currency))
        
        # Получаем свежий курс
        rate = self._fetch_fresh_rate(currency)
        if rate:
            cache_manager.set_currency_rate(currency, rate, "exchangerate-api")
            return rate
        
        # Используем fallback
        return self._get_fallback_rate(currency)
    
    def _fetch_fresh_rate(self, currency: str) -> Optional[float]:
        """Получает свежий курс из API"""
        try:
            # Основной API - exchangerate-api
            logger.debug(f"{LOGGER_PREFIX} Получаю курс USD/{currency} через exchangerate-api")
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(url, timeout=Config.REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                rates = data.get("rates", {})
                
                if currency in rates:
                    rate = float(rates[currency])
                    logger.info(f"{LOGGER_PREFIX} Получен курс USD/{currency}: {rate} (exchangerate-api)")
                    return rate
            
            # Fallback API по валютам
            return self._fetch_fallback_rate(currency)
            
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка получения курса USD/{currency}: {e}")
            return self._fetch_fallback_rate(currency)
    
    def _fetch_fallback_rate(self, currency: str) -> Optional[float]:
        """Резервные API для конкретных валют"""
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
            logger.warning(f"{LOGGER_PREFIX} Ошибка fallback API для {currency}: {e}")
            return None
    
    def _fetch_uah_rate(self) -> Optional[float]:
        """Получает курс UAH из НБУ"""
        try:
            nbu_url = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json"
            response = requests.get(nbu_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    rate = float(data[0]["rate"])
                    logger.info(f"{LOGGER_PREFIX} Получен курс USD/UAH: {rate} (НБУ)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка НБУ API: {e}")
        return None
    
    def _fetch_rub_rate(self) -> Optional[float]:
        """Получает курс RUB из ЦБ РФ"""
        try:
            cbr_url = "https://www.cbr-xml-daily.ru/daily_json.js"
            response = requests.get(cbr_url, timeout=10)
            if response.status_code == 200:
                cbr_data = response.json()
                usd_data = cbr_data.get("Valute", {}).get("USD", {})
                if usd_data:
                    rate = float(usd_data["Value"])
                    logger.info(f"{LOGGER_PREFIX} Получен курс USD/RUB: {rate} (ЦБ РФ)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка ЦБ РФ API: {e}")
        return None
    
    def _fetch_kzt_rate(self) -> Optional[float]:
        """Получает курс KZT из Нацбанка Казахстана"""
        try:
            kz_url = f"https://www.nationalbank.kz/rss/get_rates.cfm?fdate={time.strftime('%d.%m.%Y')}"
            response = requests.get(kz_url, timeout=10)
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                for item in root.findall(".//item"):
                    title = item.find("title")
                    description = item.find("description")
                    if title is not None and "USD" in title.text:
                        rate_text = description.text if description is not None else ""
                        import re
                        rate_match = re.search(r'(\d+\.?\d*)', rate_text)
                        if rate_match:
                            rate = float(rate_match.group(1))
                            logger.info(f"{LOGGER_PREFIX} Получен курс USD/KZT: {rate} (Нацбанк КЗ)")
                            return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка API Казахстана: {e}")
        return None
    
    def _fetch_eur_rate(self) -> Optional[float]:
        """Получает курс EUR через резервный API"""
        try:
            ecb_url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(ecb_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "rates" in data and "EUR" in data["rates"]:
                    rate = data["rates"]["EUR"]
                    logger.info(f"{LOGGER_PREFIX} Получен курс USD/EUR: {rate} (резервный API)")
                    return rate
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка резервного API EUR: {e}")
        return None
    
    def _get_fallback_rate(self, currency: str) -> float:
        """Возвращает fallback курс из кеша или константы"""
        # Пытаемся найти старый курс в кеше
        cached_rate = cache_manager.get_currency_rate(currency)
        if cached_rate:
            rate = cached_rate.get("rate")
            if rate and rate > 0:
                cache_age = time.time() - cached_rate.get("timestamp", 0)
                hours = int(cache_age / 3600)
                minutes = int((cache_age % 3600) / 60)
                logger.warning(f"{LOGGER_PREFIX} Используем старый курс USD/{currency}: {rate} (возраст: {hours}ч {minutes}м)")
                return rate
        
        # Используем константный fallback курс
        rate = self.FALLBACK_RATES.get(currency, 1.0)
        logger.warning(f"{LOGGER_PREFIX} Используем экстренный fallback курс USD/{currency}: {rate}")
        return rate
    
    def refresh_all_rates(self) -> dict:
        """Принудительно обновляет все курсы валют"""
        results = {}
        
        # Очищаем кеш курсов
        cache_manager.clear_currency_cache()
        
        # Обновляем все поддерживаемые валюты
        for currency in Config.SUPPORTED_CURRENCIES:
            if currency != "USD":  # USD всегда = 1.0
                try:
                    rate = self.get_currency_rate(currency)
                    results[currency] = rate
                    logger.info(f"{LOGGER_PREFIX} Обновлен курс USD/{currency}: {rate}")
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Ошибка обновления курса {currency}: {e}")
                    results[currency] = self._get_fallback_rate(currency)
        
        results["USD"] = 1.0
        return results

# Глобальный экземпляр API
currency_api = CurrencyAPI()