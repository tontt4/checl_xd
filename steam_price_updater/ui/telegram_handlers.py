"""
Модуль обработчиков Telegram для Steam Price Updater
"""

import logging
import threading
from datetime import datetime as dt
from typing import TYPE_CHECKING

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import telebot

from ..core.config import Config, LOGGER_PREFIX, CallbackButtons, settings_manager, VERSION, UUID
from ..core.lot_manager import lot_manager
from ..core.updater import lot_updater
from ..api.currency import currency_api
from ..api.steam import steam_api
from ..core.cache import cache_manager
from .wizard import lot_wizard

if TYPE_CHECKING:
    from tg_bot import CBT
else:
    from tg_bot import CBT

logger = logging.getLogger("FPC.steam_price_updater")

class TelegramHandlers:
    """Обработчики Telegram интерфейса"""
    
    def __init__(self):
        self.bot = None
        self.tg = None
    
    def setup(self, cardinal) -> None:
        """Настройка обработчиков"""
        if not cardinal.telegram:
            logger.warning(f"{LOGGER_PREFIX} Telegram бот не включен в FunPayCardinal")
            return
        
        self.tg = cardinal.telegram
        self.bot = self.tg.bot
        
        logger.info(f"{LOGGER_PREFIX} Настройка Telegram обработчиков...")
        
        # Регистрируем обработчики
        self._register_handlers()
        
        logger.info(f"{LOGGER_PREFIX} Telegram обработчики настроены")
    
    def _register_handlers(self) -> None:
        """Регистрирует все обработчики"""
        # Основные обработчики
        self.tg.cbq_handler(self.open_settings, lambda c: c.data and c.data.startswith(f"{CBT.PLUGIN_SETTINGS}:{UUID}"))
        self.tg.cbq_handler(self.show_settings, lambda c: c.data and c.data.startswith(CallbackButtons.SHOW_SETTINGS))
        self.tg.cbq_handler(self.show_lots_menu, lambda c: c.data and c.data.startswith(CallbackButtons.LOTS_MENU))
        self.tg.cbq_handler(self.show_stats, lambda c: c.data and c.data.startswith(CallbackButtons.STATS))
        
        # Обработчики лотов
        self.tg.cbq_handler(self.start_lot_wizard, lambda c: c.data and c.data.startswith(CallbackButtons.TEXT_CHANGE_LOT))
        self.tg.cbq_handler(self.edit_lot_menu, lambda c: c.data and c.data.startswith(CallbackButtons.EDIT_LOT))
        self.tg.cbq_handler(self.toggle_lot_status, lambda c: c.data and c.data.startswith(CallbackButtons.TOGGLE_LOT))
        self.tg.cbq_handler(self.delete_lot_confirm, lambda c: c.data and c.data.startswith(CallbackButtons.DELETE_LOT))
        
        # Обработчики настроек
        self.tg.cbq_handler(self.switch_currency, lambda c: c.data and c.data.startswith(CallbackButtons.CHANGE_CURRENCY))
        self.tg.cbq_handler(self.switch_steam_currency, lambda c: c.data and c.data.startswith(CallbackButtons.CHANGE_STEAM_CURRENCY))
        
        # Обработчики обновления
        self.tg.cbq_handler(self.update_now, lambda c: c.data and c.data.startswith(CallbackButtons.UPDATE_NOW))
        self.tg.cbq_handler(self.update_single_lot, lambda c: c.data and c.data.startswith("update_single_lot"))
        self.tg.cbq_handler(self.refresh_currency_rates, lambda c: c.data and c.data.startswith(CallbackButtons.REFRESH_RATES))
        
        # Обработчики мастера
        def currency_callback_handler(call):
            logger.info(f"{LOGGER_PREFIX} Вызван обработчик выбора валюты для: {call.data}")
            return lot_wizard.handle_currency_selection(call, self.bot)
        
        self.tg.cbq_handler(currency_callback_handler, lambda c: c.data and c.data.startswith("wizard_currency:"))
        logger.info(f"{LOGGER_PREFIX} Обработчик wizard_currency зарегистрирован")
        
        # Обработчик сообщений
        self.tg.msg_handler(self.handle_message)
    
    def open_settings(self, call: telebot.types.CallbackQuery) -> None:
        """Главное меню плагина"""
        try:
            # Перезагружаем лоты
            lot_manager.load_lots()
            
            keyboard = K()
            
            # Основные кнопки
            keyboard.row(
                B("📦 Лоты", callback_data=f"{CallbackButtons.LOTS_MENU}:0"),
                B("🔄 Обновить сейчас", callback_data=f"{CallbackButtons.UPDATE_NOW}:")
            )
            
            keyboard.row(
                B("⚙️ Настройки", callback_data=f"{CallbackButtons.SHOW_SETTINGS}:"),
                B("📊 Статистика", callback_data=f"{CallbackButtons.STATS}:")
            )
            
            keyboard.row(
                B("❓ Помощь", url="https://t.me/humblegodq"),
                B("◀ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:0")
            )
            
            # Статистика
            stats = lot_manager.get_lots_stats()
            active_lots = stats["active"]
            total_lots = stats["total"]
            
            text = f"🎮 <b>Steam Price Updater v{VERSION}</b>\n\n"
            
            if total_lots == 0:
                text += f"📦 <b>Лоты:</b> Не добавлены\n"
            else:
                text += f"📦 <b>Лоты:</b> {total_lots} всего, {active_lots} активных\n"
            
            hours = settings_manager.get('time', 21600) // 3600
            text += f"⏱ <b>Интервал:</b> {hours} ч\n"
            text += f"💰 <b>Валюта:</b> {settings_manager.get('currency', 'USD')}\n\n"
            
            # Курсы валют
            text += "<b>💱 Курсы валют (USD к местной):</b>\n"
            try:
                uah_rate = currency_api.get_currency_rate("UAH")
                rub_rate = currency_api.get_currency_rate("RUB")
                kzt_rate = currency_api.get_currency_rate("KZT")
                
                text += f"🇺🇦 UAH: {uah_rate:.2f}\n"
                text += f"🇷🇺 RUB: {rub_rate:.2f}\n"
                text += f"🇰🇿 KZT: {kzt_rate:.2f}\n"
            except Exception:
                text += f"💰 Курсы валют: загрузка...\n"
            
            text += f"📈 Наценка на валютный курс: {settings_manager.get('first_markup', 3)}%\n"
            text += f"💸 Маржа: {settings_manager.get('second_markup', 5)}% + ${settings_manager.get('fixed_markup', 0.5)}"
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в open_settings: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def show_settings(self, call: telebot.types.CallbackQuery) -> None:
        """Показывает настройки плагина"""
        try:
            text = f"⚙️ <b>Настройки Steam Price Updater</b>\n\n"
            
            text += f"💱 <b>Валюта расчетов:</b> {settings_manager.get('currency', 'USD')}\n"
            text += f"⏱ <b>Интервал обновления:</b> {settings_manager.get('time', 21600) // 3600} ч\n\n"
            
            text += f"<b>💰 Настройки наценок:</b>\n"
            text += f"📈 Наценка на валютный курс: {settings_manager.get('first_markup', 3)}%\n"
            text += f"📊 Маржа: {settings_manager.get('second_markup', 5)}%\n"
            text += f"💵 Фикс. наценка: ${settings_manager.get('fixed_markup', 0.5)}\n\n"
            
            text += f"<b>🔧 Дополнительно:</b>\n"
            text += f"🎮 Steam валюта по умолчанию: {Config.DEFAULT_STEAM_CURRENCY}\n"
            text += f"⏰ Пауза между лотами: {Config.LOT_PROCESSING_DELAY}с\n"
            text += f"🔄 Макс. попыток: {Config.MAX_RETRIES}\n"
            
            keyboard = K()
            keyboard.row(
                B("💱 Валюта", callback_data=f"{CallbackButtons.CHANGE_CURRENCY}:switch"),
                B("🔄 Курсы валют", callback_data=f"{CallbackButtons.REFRESH_RATES}:")
            )
            keyboard.add(B("◀ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в show_settings: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def show_lots_menu(self, call: telebot.types.CallbackQuery) -> None:
        """Показывает меню управления лотами"""
        try:
            # Перезагружаем лоты
            lot_manager.load_lots()
            
            page = int(call.data.split(":")[-1]) if call.data.split(":")[-1].isdigit() else 0
            per_page = Config.LOTS_PER_PAGE
            
            lot_items = [(lot_id, lot_data) for lot_id, lot_data in lot_manager.lots.items() if lot_id != "0"]
            total_lots = len(lot_items)
            
            # Сортируем: активные сначала
            lot_items.sort(key=lambda x: (not x[1].get("on", False), x[0]))
            
            start_idx = page * per_page
            end_idx = start_idx + per_page
            current_lots = lot_items[start_idx:end_idx]
            
            # Статистика
            active_count = len([l for _, l in lot_items if l.get("on", False)])
            text = f"📦 <b>Управление лотами</b>\n\n"
            text += f"📊 <b>Всего:</b> {total_lots} | <b>Активных:</b> {active_count}\n"
            if total_lots > per_page:
                text += f"📄 <b>Страница:</b> {page + 1}/{(total_lots - 1) // per_page + 1}\n"
            text += "\n"
            
            keyboard = K()
            
            if total_lots == 0:
                text += "📝 <i>Лоты не добавлены</i>\n\n"
                text += "💡 <b>Для начала работы:</b>\n"
                text += "1. Нажмите 'Добавить лот'\n"
                text += "2. Введите ID лота FunPay\n"
                text += "3. Настройте Steam ID игры"
            else:
                text += "<b>Ваши лоты:</b>\n"
                
                for lot_id, lot_data in current_lots:
                    game_name = steam_api.get_game_name(lot_data.get("steam_id", ""))
                    status_icon = "🟢" if lot_data.get("on", False) else "🔴"
                    
                    button_text = f"{status_icon} {game_name[:25]}"
                    callback_data = f"{CallbackButtons.EDIT_LOT}:{lot_id}"
                    keyboard.add(B(button_text, callback_data=callback_data))
            
            # Навигация
            action_buttons = []
            if page > 0:
                action_buttons.append(B("⬅ Пред", callback_data=f"{CallbackButtons.LOTS_MENU}:{page-1}"))
            if end_idx < total_lots:
                action_buttons.append(B("След ➡", callback_data=f"{CallbackButtons.LOTS_MENU}:{page+1}"))
            
            if action_buttons:
                keyboard.row(*action_buttons)
            
            # Основные кнопки
            keyboard.row(
                B("➕ Добавить лот", callback_data=f"{CallbackButtons.TEXT_CHANGE_LOT}:0"),
                B("🔄 Обновить сейчас", callback_data=f"{CallbackButtons.UPDATE_NOW}:")
            )
            keyboard.add(B("◀ Главное меню", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в show_lots_menu: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def start_lot_wizard(self, call: telebot.types.CallbackQuery) -> None:
        """Запускает мастер создания лота"""
        lot_wizard.start_wizard(call, self.bot)
    
    def edit_lot_menu(self, call: telebot.types.CallbackQuery) -> None:
        """Показывает меню редактирования лота"""
        try:
            lot_id = call.data.split(":")[-1]
            
            if lot_id not in lot_manager.lots:
                self.bot.answer_callback_query(call.id, "❌ Лот не найден")
                return
            
            lot_data = lot_manager.lots[lot_id]
            game_name = steam_api.get_game_name(lot_data.get("steam_id", ""))
            
            status_icon = "🟢" if lot_data.get("on", False) else "🔴"
            text = f"{status_icon} <b>Лот #{lot_id}</b>\n"
            text += f"🎮 <b>{game_name}</b>\n\n"
            
            # Данные Steam
            steam_id = lot_data.get("steam_id", "N/A")
            steam_currency = lot_data.get("steam_currency", "UAH")
            
            if str(steam_id).startswith("sub_"):
                text += f"📦 <b>Steam Sub ID:</b> {steam_id[4:]}\n"
                text += f"💿 <b>Тип:</b> DLC/Package\n"
            else:
                text += f"🎯 <b>Steam App ID:</b> {steam_id}\n"
                text += f"🎮 <b>Тип:</b> Игра\n"
            
            text += f"💱 <b>Валюта Steam:</b> {steam_currency}\n\n"
            
            # Ценовые настройки
            min_price = lot_data.get("min", 1.0)
            max_price = lot_data.get("max", 5000.0)
            last_price = lot_data.get("last_price", 0)
            last_steam_price = lot_data.get("last_steam_price", 0)
            
            text += "💰 <b>Ценовые настройки:</b>\n"
            text += f"🔻 Мин. цена: ${min_price:.2f}\n"
            text += f"🔺 Макс. цена: ${max_price:.2f}\n"
            
            if last_price > 0:
                text += f"💵 Текущая цена: ${last_price:.2f}\n"
            if last_steam_price > 0:
                text += f"🎮 Steam цена: {last_steam_price:.2f} {steam_currency}\n"
            
            text += "\n"
            
            # Обновления
            last_update = lot_data.get("last_update", 0)
            global_interval_hours = settings_manager.get("time", 21600) // 3600
            
            text += "⏰ <b>Обновления:</b>\n"
            text += f"🔄 Интервал: {global_interval_hours} ч (глобальный)\n"
            
            if last_update > 0:
                last_update_str = dt.fromtimestamp(last_update).strftime("%d.%m %H:%M")
                text += f"📅 Последнее: {last_update_str}\n"
            else:
                text += f"📅 Последнее: Никогда\n"
            
            # Кнопки
            keyboard = K()
            
            status_text = "❌ Выключить" if lot_data.get("on", False) else "✅ Включить"
            keyboard.add(B(status_text, callback_data=f"{CallbackButtons.TOGGLE_LOT}:{lot_id}"))
            
            keyboard.row(
                B("💱 Валюта", callback_data=f"{CallbackButtons.CHANGE_STEAM_CURRENCY}:{lot_id}"),
                B("🔄 Обновить лот", callback_data=f"update_single_lot:{lot_id}")
            )
            
            keyboard.row(
                B("🗑 Удалить", callback_data=f"{CallbackButtons.DELETE_LOT}:{lot_id}"),
                B("◀ К лотам", callback_data=f"{CallbackButtons.LOTS_MENU}:0")
            )
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в edit_lot_menu: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def toggle_lot_status(self, call: telebot.types.CallbackQuery) -> None:
        """Переключает статус лота"""
        try:
            lot_id = call.data.split(":")[-1]
            
            if lot_id not in lot_manager.lots:
                self.bot.answer_callback_query(call.id, "❌ Лот не найден")
                return
            
            lot_manager.lots[lot_id]["on"] = not lot_manager.lots[lot_id].get("on", False)
            lot_manager.save_lots()
            
            status = "включен" if lot_manager.lots[lot_id]["on"] else "выключен"
            self.bot.answer_callback_query(call.id, f"Лот {status}")
            
            self.edit_lot_menu(call)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в toggle_lot_status: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def delete_lot_confirm(self, call: telebot.types.CallbackQuery) -> None:
        """Удаляет лот"""
        try:
            lot_id = call.data.split(":")[-1]
            
            if lot_manager.delete_lot(lot_id):
                self.bot.answer_callback_query(call.id, f"Лот {lot_id} удален")
                self.show_lots_menu(call)
            else:
                self.bot.answer_callback_query(call.id, "❌ Ошибка удаления")
                
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в delete_lot_confirm: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def switch_currency(self, call: telebot.types.CallbackQuery) -> None:
        """Переключает валюту аккаунта"""
        try:
            account_currencies = Config.ACCOUNT_CURRENCIES
            
            current_currency = settings_manager.get("currency", "USD")
            try:
                current_index = account_currencies.index(current_currency)
                new_currency = account_currencies[(current_index + 1) % len(account_currencies)]
            except ValueError:
                new_currency = "USD"
            
            settings_manager.set("currency", new_currency)
            settings_manager.save_settings()
            
            currency_symbols = {"USD": "$", "RUB": "₽", "EUR": "€"}
            symbol = currency_symbols.get(new_currency, new_currency)
            self.bot.answer_callback_query(call.id, f"Валюта: {symbol} {new_currency}")
            
            self.show_settings(call)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в switch_currency: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def switch_steam_currency(self, call: telebot.types.CallbackQuery) -> None:
        """Переключает валюту Steam для лота"""
        try:
            lot_id = call.data.split(":")[-1]
            
            if lot_id not in lot_manager.lots:
                self.bot.answer_callback_query(call.id, "❌ Лот не найден")
                return
            
            currencies = Config.SUPPORTED_CURRENCIES
            current_currency = lot_manager.lots[lot_id].get("steam_currency", "UAH")
            
            try:
                current_index = currencies.index(current_currency)
                new_currency = currencies[(current_index + 1) % len(currencies)]
            except ValueError:
                new_currency = "UAH"
            
            lot_manager.lots[lot_id]["steam_currency"] = new_currency
            lot_manager.save_lots()
            
            self.bot.answer_callback_query(call.id, f"Валюта Steam: {new_currency}")
            self.edit_lot_menu(call)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в switch_steam_currency: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def update_now(self, call: telebot.types.CallbackQuery) -> None:
        """Запускает принудительное обновление всех лотов"""
        try:
            active_lots = lot_manager.get_active_lots()
            
            if not active_lots:
                self.bot.answer_callback_query(call.id, "Нет активных лотов")
                return
            
            self.bot.answer_callback_query(call.id, "Обновление запущено...")
            
            def update_thread():
                results = lot_updater.update_all_lots()
                result_text = f"Обновление завершено!\nОбновлено: {results['updated']}\nОшибок: {results['failed']}"
                self.bot.send_message(call.message.chat.id, result_text)
            
            threading.Thread(target=update_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в update_now: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def update_single_lot(self, call: telebot.types.CallbackQuery) -> None:
        """Обновляет один лот"""
        try:
            lot_id = call.data.split(":")[-1]
            
            self.bot.answer_callback_query(call.id, f"🔄 Обновляю лот {lot_id}...")
            
            def update_thread():
                success = lot_updater.update_lot_now(lot_id)
                if success:
                    self.bot.send_message(call.message.chat.id, f"✅ Лот {lot_id} успешно обновлен!")
                else:
                    self.bot.send_message(call.message.chat.id, f"❌ Ошибка обновления лота {lot_id}")
            
            threading.Thread(target=update_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в update_single_lot: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def refresh_currency_rates(self, call: telebot.types.CallbackQuery) -> None:
        """Обновляет курсы валют"""
        try:
            self.bot.answer_callback_query(call.id, "Обновляю курсы...")
            
            def refresh_thread():
                try:
                    results = currency_api.refresh_all_rates()
                    
                    result_text = f"💱 Курсы валют обновлены:\n\n"
                    for currency, rate in results.items():
                        if currency != "USD":
                            result_text += f"🇺🇸 USD/{currency}: {rate:.2f}\n"
                    result_text += f"\n🕐 {dt.now().strftime('%H:%M:%S')}"
                    
                    self.bot.send_message(call.message.chat.id, result_text)
                    
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Ошибка обновления курсов: {e}")
                    self.bot.send_message(call.message.chat.id, "❌ Ошибка обновления курсов")
            
            threading.Thread(target=refresh_thread, daemon=True).start()
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в refresh_currency_rates: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def show_stats(self, call: telebot.types.CallbackQuery) -> None:
        """Показывает статистику"""
        try:
            stats = lot_manager.get_lots_stats()
            cache_stats = cache_manager.get_cache_stats()
            
            text = f"📊 Статистика Steam Price Updater\n\n"
            text += f"📦 Всего лотов: {stats['total']}\n"
            text += f"✅ Активных: {stats['active']}\n"
            text += f"💰 Лотов с ценами: {stats['with_prices']}\n"
            text += f"🔄 Кеш: {cache_stats['total']} записей\n"
            text += f"  • Steam цены: {cache_stats['steam_prices']}\n"
            text += f"  • Курсы валют: {cache_stats['currency_rates']}\n"
            text += f"  • Названия игр: {cache_stats['game_names']}\n"
            
            # Статус обновления
            updater_status = lot_updater.get_status()
            text += f"\n🔄 Обработчик: {'работает' if updater_status['running'] else 'остановлен'}\n"
            
            keyboard = K()
            keyboard.add(B("◀ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:0"))
            
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                      reply_markup=keyboard, parse_mode="HTML")
            self.bot.answer_callback_query(call.id)
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в show_stats: {e}")
            self.bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def handle_message(self, message: telebot.types.Message) -> None:
        """Обрабатывает сообщения"""
        try:
            # Сначала пытаемся обработать через мастер
            if lot_wizard.handle_message(message, self.bot):
                return
            
            # Здесь можно добавить обработку других типов сообщений
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка в handle_message: {e}")

# Глобальный экземпляр обработчиков
telegram_handlers = TelegramHandlers()