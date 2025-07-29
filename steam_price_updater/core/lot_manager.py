"""
Модуль для управления лотами
"""

import json
import os
import time
import logging
from typing import Dict, Any, Optional, List

from .config import Config, LOGGER_PREFIX, settings_manager
from ..api.steam import steam_api
from .price_calculator import price_calculator

logger = logging.getLogger("FPC.steam_price_updater")

class LotManager:
    """Менеджер лотов"""
    
    def __init__(self):
        self.lots = {}
        self.lots_file = "storage/plugins/steam_price_updater_lots.json"
        self.wizard_states = {}
        self.wizard_file = "storage/plugins/steam_price_updater_wizard.json"
    
    def load_lots(self) -> None:
        """Загружает лоты из файла"""
        load_attempts = [
            ("storage/plugins/steam_price_updater_lots.json", "основное расположение"),
            ("steam_price_updater_lots.json", "текущая директория"),
            ("/tmp/steam_price_updater_lots.json", "временная директория"),
            ("./lots_backup.json", "резервная копия")
        ]
        
        lots_file = None
        for attempt_file, description in load_attempts:
            if os.path.exists(attempt_file):
                lots_file = attempt_file
                logger.info(f"{LOGGER_PREFIX} Найден файл лотов: {lots_file} ({description})")
                break
        
        if lots_file:
            try:
                with open(lots_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        self.lots = json.loads(content)
                        
                        # Миграция старых данных
                        self._migrate_lot_data()
                        
                        logger.info(f"{LOGGER_PREFIX} Загружено {len(self.lots)} лотов")
                    else:
                        self.lots = {}
            except Exception as e:
                logger.warning(f"{LOGGER_PREFIX} Ошибка загрузки лотов: {e}")
                self.lots = {}
        else:
            logger.info(f"{LOGGER_PREFIX} Файл лотов не найден, создаем новый")
            self.lots = {}
    
    def _migrate_lot_data(self) -> None:
        """Миграция старых данных лотов"""
        for lot_id, lot_data in self.lots.items():
            # Миграция steam_app_id → steam_id
            if "steam_id" not in lot_data and "steam_app_id" in lot_data:
                self.lots[lot_id]["steam_id"] = str(lot_data["steam_app_id"])
            
            # Установка значений по умолчанию
            defaults = {
                "steam_app_id": 0,
                "steam_id": "730",
                "steam_currency": "UAH",
                "min": settings_manager.get("min_price", 1.0),
                "max": settings_manager.get("max_price", 5000.0),
                "last_steam_price": 0,
                "last_price": 0,
                "last_update": 0,
                "on": True
            }
            
            for key, default_value in defaults.items():
                if key not in lot_data:
                    self.lots[lot_id][key] = default_value
    
    def save_lots(self) -> bool:
        """Сохраняет лоты в файл"""
        try:
            logger.debug(f"{LOGGER_PREFIX} Сохранение {len(self.lots)} лотов")
            
            # Подготовка данных
            json_data = json.dumps(self.lots, indent=4, ensure_ascii=False)
            
            # Попытки сохранения
            save_attempts = [
                ("storage/plugins/steam_price_updater_lots.json", "основное расположение"),
                ("steam_price_updater_lots.json", "текущая директория"),
                ("/tmp/steam_price_updater_lots.json", "временная директория"),
                ("./lots_backup.json", "резервная копия")
            ]
            
            for attempt_file, description in save_attempts:
                try:
                    # Создаем директорию если нужно
                    if "/" in attempt_file:
                        dir_path = os.path.dirname(attempt_file)
                        if dir_path and not os.path.exists(dir_path):
                            os.makedirs(dir_path, exist_ok=True)
                    
                    # Сохраняем файл
                    with open(attempt_file, "w", encoding="utf-8") as f:
                        f.write(json_data)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except (OSError, AttributeError):
                            pass
                    
                    # Проверяем что файл создался
                    if os.path.exists(attempt_file):
                        file_size = os.path.getsize(attempt_file)
                        logger.info(f"{LOGGER_PREFIX} ✅ Лоты сохранены в {attempt_file} (размер: {file_size} байт)")
                        return True
                        
                except (PermissionError, OSError, IOError) as e:
                    logger.warning(f"{LOGGER_PREFIX} Не удалось сохранить в {attempt_file}: {e}")
                    continue
            
            logger.error(f"{LOGGER_PREFIX} ❌ Не удалось сохранить лоты ни в одно расположение!")
            return False
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} ❌ Критическая ошибка сохранения лотов: {e}")
            return False
    
    def validate_lot_data(self, lot_data: Dict[str, Any]) -> bool:
        """Валидирует данные лота"""
        required_fields = ["steam_id", "steam_currency", "min", "max"]
        
        # Проверяем обязательные поля
        for field in required_fields:
            if field not in lot_data:
                logger.debug(f"{LOGGER_PREFIX} Отсутствует поле: {field}")
                return False
        
        # Проверяем Steam ID
        steam_id = lot_data.get("steam_id")
        if not steam_id or steam_id == "":
            logger.debug(f"{LOGGER_PREFIX} Пустой steam_id")
            return False
        
        # Проверяем цены
        min_price = lot_data.get("min")
        max_price = lot_data.get("max")
        
        if not isinstance(min_price, (int, float)) or not isinstance(max_price, (int, float)):
            logger.debug(f"{LOGGER_PREFIX} Неверный тип цен")
            return False
        
        if min_price <= 0 or max_price <= 0:
            logger.debug(f"{LOGGER_PREFIX} Отрицательные цены")
            return False
        
        if min_price > max_price:
            logger.debug(f"{LOGGER_PREFIX} min больше max")
            return False
        
        return True
    
    def add_lot(self, lot_id: str, steam_id: str, steam_currency: str, min_price: float, max_price: float) -> bool:
        """Добавляет новый лот"""
        try:
            # Валидируем Steam ID
            is_valid, id_type, clean_id = steam_api.validate_steam_id(steam_id)
            if not is_valid:
                logger.warning(f"{LOGGER_PREFIX} Неверный Steam ID: {steam_id}")
                return False
            
            # Создаем лот
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
            
            logger.info(f"{LOGGER_PREFIX} Добавлен лот {lot_id}: {steam_id} ({steam_currency})")
            return self.save_lots()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка добавления лота: {e}")
            return False
    
    def update_lot_price(self, lot_id: str, cardinal) -> bool:
        """Обновляет цену лота"""
        try:
            if lot_id not in self.lots:
                logger.warning(f"{LOGGER_PREFIX} Лот {lot_id} не найден")
                return False
            
            lot_data = self.lots[lot_id]
            
            # Валидация данных лота
            if not self.validate_lot_data(lot_data):
                logger.warning(f"{LOGGER_PREFIX} Невалидные данные лота {lot_id}")
                return False
            
            # Получаем данные лота
            steam_id = lot_data.get("steam_id")
            steam_currency = lot_data.get("steam_currency", "UAH")
            
            # Получаем цену Steam с повторными попытками
            steam_price = None
            for attempt in range(Config.MAX_RETRIES):
                steam_price = steam_api.get_steam_price(steam_id, steam_currency)
                if steam_price and steam_price > 0:
                    break
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.LOT_PROCESSING_DELAY)
            
            if not steam_price or steam_price <= 0:
                logger.warning(f"{LOGGER_PREFIX} Не удалось получить цену Steam для лота {lot_id}")
                return False
            
            # Рассчитываем новую цену
            new_price = price_calculator.calculate_lot_price(steam_price, steam_currency)
            if new_price <= 0:
                logger.error(f"{LOGGER_PREFIX} Неверная вычисленная цена для лота {lot_id}: {new_price}")
                return False
            
            # Применяем ограничения лота
            lot_min = lot_data.get("min", settings_manager.get("min_price", 1.0))
            lot_max = lot_data.get("max", settings_manager.get("max_price", 5000.0))
            new_price = max(lot_min, min(new_price, lot_max))
            
            # Обновляем цену через Cardinal API
            success = self._change_cardinal_price(cardinal, lot_id, new_price)
            if success:
                # Обновляем данные лота
                self.lots[lot_id]["last_steam_price"] = steam_price
                self.lots[lot_id]["last_price"] = new_price
                self.lots[lot_id]["last_update"] = time.time()
                
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} обновлен: Steam {steam_price} {steam_currency} → ${new_price:.2f}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка обновления лота {lot_id}: {e}")
            return False
    
    def _change_cardinal_price(self, cardinal, lot_id: str, new_price: float) -> bool:
        """Изменяет цену через Cardinal API"""
        try:
            # Получаем поля лота
            lot_fields = cardinal.account.get_lot_fields(int(lot_id))
            if lot_fields is None:
                logger.error(f"{LOGGER_PREFIX} Лот {lot_id} не найден в Cardinal")
                # Удаляем недоступный лот
                if lot_id in self.lots:
                    del self.lots[lot_id]
                    self.save_lots()
                return False
            
            # Проверяем текущую цену
            old_price = lot_fields.price
            if old_price is None:
                logger.error(f"{LOGGER_PREFIX} Текущая цена лота {lot_id} равна None")
                return False
            
            logger.debug(f"{LOGGER_PREFIX} Лот {lot_id}: текущая цена {old_price:.2f}, новая {new_price:.2f}")
            
            # Обновляем только если цена реально изменилась
            if abs(round(new_price, 2) - round(old_price, 2)) >= 0.005:
                lot_fields.price = new_price
                cardinal.account.save_lot(lot_fields)
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} обновлён: {old_price:.2f} → {new_price:.2f}")
                return True
            else:
                logger.info(f"{LOGGER_PREFIX} Лот {lot_id} остался на {old_price:.2f}")
                return True
                
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка изменения цены лота {lot_id}: {e}")
            return False
    
    def get_lot(self, lot_id: str) -> Optional[Dict[str, Any]]:
        """Получает данные лота"""
        return self.lots.get(lot_id)
    
    def delete_lot(self, lot_id: str) -> bool:
        """Удаляет лот"""
        if lot_id in self.lots:
            del self.lots[lot_id]
            logger.info(f"{LOGGER_PREFIX} Лот {lot_id} удален")
            return self.save_lots()
        return False
    
    def get_active_lots(self) -> List[str]:
        """Возвращает список активных лотов"""
        return [lot_id for lot_id, lot_data in self.lots.items()
                if lot_data.get("on", False) and lot_id != "0"]
    
    def get_lots_stats(self) -> Dict[str, int]:
        """Возвращает статистику лотов"""
        total = len(self.lots)
        active = len(self.get_active_lots())
        with_prices = len([l for l in self.lots.values() if l.get("last_price", 0) > 0])
        
        return {
            "total": total,
            "active": active,
            "with_prices": with_prices
        }

# Глобальный экземпляр менеджера
lot_manager = LotManager()