"""
Модуль для расчета цен лотов
"""

import logging
from typing import Union

from .config import LOGGER_PREFIX, settings_manager
from ..api.currency import currency_api

logger = logging.getLogger("FPC.steam_price_updater")

class PriceCalculator:
    """Калькулятор цен для лотов"""
    
    def calculate_lot_price(self, steam_price: Union[float, int, str], steam_currency: str = "UAH") -> float:
        """
        Вычисляет цену лота с учетом валюты FunPay аккаунта
        
        Логика наценки:
        - first_markup% наценка на валютный курс
        - second_markup% маржа прибыли  
        - fixed_markup единиц валюты фиксированная наценка
        """
        # Валидация входных данных
        try:
            if isinstance(steam_price, str):
                steam_price = float(steam_price)
            elif not isinstance(steam_price, (int, float)):
                logger.warning(f"{LOGGER_PREFIX} Неверный тип данных для steam_price: {type(steam_price)}")
                return 0.0
            
            steam_price = float(steam_price)
            if steam_price < 0:
                logger.warning(f"{LOGGER_PREFIX} Отрицательная цена Steam: {steam_price}")
                return 0.0
                
        except (ValueError, TypeError) as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка преобразования steam_price: {e}")
            return 0.0
        
        # Минимальная цена для бесплатных игр
        if steam_price <= 0.01:
            return settings_manager.get("min_price", 1.0)
        
        try:
            # Получаем валюту аккаунта
            account_currency = settings_manager.get("currency", "USD")
            
            # Конвертируем цену в валюту аккаунта
            base_price = self._convert_to_account_currency(steam_price, steam_currency, account_currency)
            
            if base_price <= 0:
                logger.error(f"{LOGGER_PREFIX} Ошибка конвертации валюты")
                return 0.0
            
            # Применяем наценки
            final_price = self._apply_markups(base_price)
            
            # Применяем ограничения по цене
            final_price = self._apply_price_limits(final_price)
            
            # Округляем до 2 знаков
            final_price = round(final_price, 2)
            
            # Логируем расчет
            currency_symbol = {"USD": "$", "RUB": "₽", "EUR": "€"}.get(account_currency, account_currency)
            logger.debug(f"{LOGGER_PREFIX} Расчет цены: {steam_price} {steam_currency} → {base_price:.4f} {account_currency} → {currency_symbol}{final_price:.2f}")
            
            return final_price
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка расчета цены: {e}")
            return 0.0
    
    def _convert_to_account_currency(self, steam_price: float, steam_currency: str, account_currency: str) -> float:
        """Конвертирует цену Steam в валюту аккаунта"""
        
        # Если валюты одинаковые, конвертация не нужна
        if steam_currency == account_currency:
            return steam_price
        
        # Конвертируем через USD как базовую валюту
        if account_currency == "USD":
            # Steam currency → USD
            if steam_currency == "USD":
                return steam_price
            else:
                currency_rate = currency_api.get_currency_rate(steam_currency)
                if currency_rate <= 0:
                    logger.warning(f"{LOGGER_PREFIX} Неверный курс валюты: {currency_rate}")
                    return 0.0
                return steam_price / currency_rate
        else:
            # Steam currency → USD → Account currency
            if steam_currency == "USD":
                price_usd = steam_price
            else:
                steam_rate = currency_api.get_currency_rate(steam_currency)
                if steam_rate <= 0:
                    logger.warning(f"{LOGGER_PREFIX} Неверный курс Steam валюты: {steam_rate}")
                    return 0.0
                price_usd = steam_price / steam_rate
            
            # USD → Account currency
            account_rate = currency_api.get_currency_rate(account_currency)
            if account_rate <= 0:
                logger.warning(f"{LOGGER_PREFIX} Неверный курс валюты аккаунта: {account_rate}")
                return 0.0
            return price_usd * account_rate
    
    def _apply_markups(self, base_price: float) -> float:
        """Применяет наценки к базовой цене"""
        
        # Наценка на валютный курс
        first_markup = settings_manager.get("first_markup", 3.0)
        price_with_currency_markup = base_price * (1 + first_markup / 100)
        
        # Маржа прибыли + фиксированная наценка
        second_markup = settings_manager.get("second_markup", 5.0)
        fixed_markup = settings_manager.get("fixed_markup", 0.5)
        final_price = price_with_currency_markup * (1 + second_markup / 100) + fixed_markup
        
        return final_price
    
    def _apply_price_limits(self, price: float) -> float:
        """Применяет ограничения по минимальной и максимальной цене"""
        min_price = settings_manager.get("min_price", 1.0)
        max_price = settings_manager.get("max_price", 5000.0)
        
        return max(min_price, min(price, max_price))

# Глобальный экземпляр калькулятора
price_calculator = PriceCalculator()