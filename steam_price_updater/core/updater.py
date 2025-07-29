"""
Модуль основного цикла обновления лотов
"""

import time
import threading
import logging
from typing import Optional

from .config import Config, LOGGER_PREFIX, settings_manager
from .lot_manager import lot_manager
from ..core.cache import cache_manager

logger = logging.getLogger("FPC.steam_price_updater")

class LotUpdater:
    """Основной обработчик обновлений лотов"""
    
    def __init__(self):
        self._cardinal = None
        self._running = False
        self._thread = None
        self._last_check_times = {}
    
    def start(self, cardinal) -> None:
        """Запускает основной цикл обработки"""
        if self._running:
            logger.info(f"{LOGGER_PREFIX} Обработчик уже запущен")
            return
        
        self._cardinal = cardinal
        self._running = True
        
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"{LOGGER_PREFIX} Запущен основной цикл обработки лотов")
    
    def stop(self) -> None:
        """Останавливает основной цикл"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"{LOGGER_PREFIX} Основной цикл остановлен")
    
    def _main_loop(self) -> None:
        """Основной цикл обработки лотов"""
        while self._running:
            try:
                current_time = time.time()
                processed_count = 0
                
                # Обрабатываем активные лоты
                active_lots = lot_manager.get_active_lots()
                
                for lot_id in active_lots:
                    if not self._running:
                        break
                    
                    # Проверяем нужно ли обновлять лот
                    if self._should_update_lot(lot_id, current_time):
                        logger.info(f"{LOGGER_PREFIX} Обрабатываю лот {lot_id}")
                        
                        # Обновляем время последней проверки
                        self._last_check_times[lot_id] = current_time
                        
                        # Обновляем лот
                        try:
                            success = lot_manager.update_lot_price(lot_id, self._cardinal)
                            if success:
                                processed_count += 1
                            
                            # Задержка между лотами
                            time.sleep(Config.LOT_PROCESSING_DELAY)
                            
                        except Exception as e:
                            logger.error(f"{LOGGER_PREFIX} Ошибка обновления лота {lot_id}: {e}")
                
                # Сохраняем лоты если что-то обработали
                if processed_count > 0:
                    lot_manager.save_lots()
                    logger.info(f"{LOGGER_PREFIX} Цикл завершен, обработано лотов: {processed_count}")
                
                # Очищаем устаревший кеш
                self._cleanup_cache()
                
            except Exception as e:
                logger.error(f"{LOGGER_PREFIX} Критическая ошибка в основном цикле: {e}")
            
            # Пауза между циклами
            time.sleep(Config.CYCLE_PAUSE)
    
    def _should_update_lot(self, lot_id: str, current_time: float) -> bool:
        """Проверяет нужно ли обновлять лот"""
        global_interval = settings_manager.get("time", 21600)  # 6 часов по умолчанию
        last_check = self._last_check_times.get(lot_id, 0)
        
        return current_time - last_check >= global_interval
    
    def _cleanup_cache(self) -> None:
        """Очищает устаревший кеш"""
        try:
            expired_count = cache_manager.cache.clear_expired()
            if expired_count > 0:
                logger.debug(f"{LOGGER_PREFIX} Очищено {expired_count} устаревших записей кеша")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка очистки кеша: {e}")
    
    def update_lot_now(self, lot_id: str) -> bool:
        """Принудительно обновляет конкретный лот"""
        try:
            if not self._cardinal:
                logger.error(f"{LOGGER_PREFIX} Cardinal недоступен")
                return False
            
            if lot_id not in lot_manager.lots:
                logger.error(f"{LOGGER_PREFIX} Лот {lot_id} не найден")
                return False
            
            lot_data = lot_manager.lots[lot_id]
            if not lot_data.get("on", False):
                logger.error(f"{LOGGER_PREFIX} Лот {lot_id} выключен")
                return False
            
            logger.info(f"{LOGGER_PREFIX} Принудительное обновление лота {lot_id}")
            success = lot_manager.update_lot_price(lot_id, self._cardinal)
            
            if success:
                lot_manager.save_lots()
                # Обновляем время последней проверки
                self._last_check_times[lot_id] = time.time()
            
            return success
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка принудительного обновления лота {lot_id}: {e}")
            return False
    
    def update_all_lots(self) -> dict:
        """Принудительно обновляет все активные лоты"""
        results = {"updated": 0, "failed": 0, "total": 0}
        
        try:
            if not self._cardinal:
                logger.error(f"{LOGGER_PREFIX} Cardinal недоступен")
                return results
            
            active_lots = lot_manager.get_active_lots()
            results["total"] = len(active_lots)
            
            logger.info(f"{LOGGER_PREFIX} Принудительное обновление {len(active_lots)} лотов")
            
            for lot_id in active_lots:
                try:
                    success = lot_manager.update_lot_price(lot_id, self._cardinal)
                    if success:
                        results["updated"] += 1
                        # Обновляем время последней проверки
                        self._last_check_times[lot_id] = time.time()
                    else:
                        results["failed"] += 1
                    
                    # Задержка между лотами
                    time.sleep(Config.LOT_PROCESSING_DELAY)
                    
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Ошибка обновления лота {lot_id}: {e}")
                    results["failed"] += 1
            
            # Сохраняем результаты
            lot_manager.save_lots()
            
            logger.info(f"{LOGGER_PREFIX} Принудительное обновление завершено: {results['updated']} успешно, {results['failed']} ошибок")
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка массового обновления: {e}")
        
        return results
    
    def get_status(self) -> dict:
        """Возвращает статус обработчика"""
        return {
            "running": self._running,
            "lots_tracked": len(self._last_check_times),
            "cardinal_available": self._cardinal is not None
        }

# Глобальный экземпляр обработчика
lot_updater = LotUpdater()