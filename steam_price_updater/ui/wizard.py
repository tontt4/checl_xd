"""
Мастер создания лотов
"""

import json
import os
import logging
from typing import Dict, Any, Optional

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import telebot

from ..core.config import LOGGER_PREFIX, CallbackButtons, settings_manager
from ..core.lot_manager import lot_manager
from ..api.steam import steam_api
from ..core.price_calculator import price_calculator

logger = logging.getLogger("FPC.steam_price_updater")

class LotWizard:
    """Мастер создания лотов через Telegram"""
    
    def __init__(self):
        self.wizard_states = {}
        self.wizard_file = "storage/plugins/steam_price_updater_wizard.json"
        self.load_wizard_states()
    
    def load_wizard_states(self) -> None:
        """Загружает состояния мастера из файла"""
        try:
            if os.path.exists(self.wizard_file):
                with open(self.wizard_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        self.wizard_states = json.loads(content)
                        logger.debug(f"{LOGGER_PREFIX} Загружены состояния мастера: {len(self.wizard_states)} состояний")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка загрузки состояний мастера: {e}")
            self.wizard_states = {}
    
    def save_wizard_states(self) -> None:
        """Сохраняет состояния мастера в файл"""
        try:
            os.makedirs("storage/plugins", exist_ok=True)
            with open(self.wizard_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.wizard_states, indent=4, ensure_ascii=False))
                f.flush()
            logger.debug(f"{LOGGER_PREFIX} Состояния мастера сохранены: {len(self.wizard_states)} состояний")
        except Exception as e:
            logger.warning(f"{LOGGER_PREFIX} Ошибка сохранения состояний мастера: {e}")
    
    def get_user_key(self, obj) -> str:
        """Генерирует ключ пользователя"""
        # Обрабатываем как CallbackQuery, так и Message
        if hasattr(obj, 'message'):  # CallbackQuery
            return f"{obj.message.chat.id}_{obj.from_user.id}"
        else:  # Message
            return f"{obj.chat.id}_{obj.from_user.id}"
    
    def start_wizard(self, call: telebot.types.CallbackQuery, bot) -> None:
        """Запускает мастер создания лота"""
        try:
            user_key = self.get_user_key(call)
            
            # Сохраняем состояние
            self.wizard_states[user_key] = {"step": "lot_id"}
            self.save_wizard_states()
            
            text = "🧙‍♂️ <b>Мастер добавления лота</b>\n\n"
            text += "📋 <b>Шаг 1 из 4: ID лота</b>\n\n"
            text += "Введите ID лота с FunPay:\n"
            text += "• Найдите лот на funpay.com\n"
            text += "• Скопируйте цифры из URL\n"
            text += "• Например: из funpay.com/lots/offer?id=<b>12345</b>\n"
            text += "• Введите просто: <code>12345</code>\n\n"
            text += "💡 Это нужно для связи с вашим лотом на FunPay"
            
            keyboard = K()
            keyboard.add(B("◀ Отмена", callback_data=f"{CallbackButtons.LOTS_MENU}:0"))
            
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                  reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id, "🧙‍♂️ Начинаем мастер!")
            
            logger.info(f"{LOGGER_PREFIX} Мастер запущен для пользователя {user_key}")
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка запуска мастера: {e}")
            bot.answer_callback_query(call.id, "❌ Ошибка")
    
    def handle_message(self, message: telebot.types.Message, bot) -> bool:
        """Обрабатывает сообщения мастера"""
        try:
            if not message.text or not message.from_user:
                return False
            
            user_key = self.get_user_key(message)
            
            if user_key not in self.wizard_states:
                return False
            
            state_data = self.wizard_states[user_key]
            step = state_data.get("step")
            text = message.text.strip()
            
            logger.info(f"{LOGGER_PREFIX} Обработка шага мастера: {step}, текст: '{text}'")
            
            if step == "lot_id":
                return self._handle_lot_id(message, bot, user_key, text)
            elif step == "steam_id":
                return self._handle_steam_id(message, bot, user_key, text)
            elif step == "max_price":
                return self._handle_max_price(message, bot, user_key, text)
            
            return False
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка обработки сообщения мастера: {e}")
            return False
    
    def _handle_lot_id(self, message, bot, user_key: str, text: str) -> bool:
        """Обрабатывает ввод ID лота"""
        if not text.isdigit():
            bot.reply_to(message, "❌ ID лота должен содержать только цифры")
            return True
        
        if text in lot_manager.lots:
            bot.reply_to(message, f"❌ Лот {text} уже настроен")
            return True
        
        # Переходим к следующему шагу
        self.wizard_states[user_key] = {"step": "steam_id", "lot_id": text}
        self.save_wizard_states()
        
        text_msg = "🧙‍♂️ <b>Мастер добавления лота</b>\n\n"
        text_msg += "📋 <b>Шаг 2 из 4: Steam ID</b>\n\n"
        text_msg += f"✅ ID лота: <code>{text}</code>\n\n"
        text_msg += "Введите Steam ID игры:\n"
        text_msg += "• Для обычных игр: <code>730</code> (CS2)\n"
        text_msg += "• Для DLC: <code>sub_12345</code>\n"
        text_msg += "• Найти можно на steamdb.info"
        
        keyboard = K()
        keyboard.add(B("◀ К лотам", callback_data=f"{CallbackButtons.LOTS_MENU}:0"))
        
        bot.send_message(message.chat.id, text_msg, reply_markup=keyboard, parse_mode="HTML")
        return True
    
    def _handle_steam_id(self, message, bot, user_key: str, text: str) -> bool:
        """Обрабатывает ввод Steam ID"""
        state_data = self.wizard_states[user_key]
        lot_id = state_data.get("lot_id")
        
        # Валидируем Steam ID
        is_valid, id_type, clean_id = steam_api.validate_steam_id(text)
        if not is_valid:
            bot.reply_to(message, "❌ Неверный формат Steam ID. Используйте числа для игр или sub_12345 для DLC")
            return True
        
        # Получаем и проверяем цену
        steam_price = steam_api.get_steam_price(text, "UAH")
        if steam_price is None:
            bot.reply_to(message, "❌ Не удалось получить цену из Steam API. Проверьте Steam ID или попробуйте позже.")
            return True
        
        if steam_price == 0.0:
            bot.reply_to(message, "❌ Это бесплатная игра или DLC. Нельзя создать лот для бесплатного контента.")
            return True
        
        # Рассчитываем минимальную цену
        min_price = price_calculator.calculate_lot_price(steam_price, "UAH")
        
        # Переходим к выбору валюты
        self.wizard_states[user_key] = {
            "step": "currency",
            "lot_id": lot_id,
            "steam_id": text,
            "min_price": min_price
        }
        self.save_wizard_states()
        
        text_msg = "🧙‍♂️ <b>Мастер добавления лота</b>\n\n"
        text_msg += "📋 <b>Шаг 3 из 4: Валюта Steam</b>\n\n"
        text_msg += f"✅ ID лота: <code>{lot_id}</code>\n"
        text_msg += f"✅ Steam ID: <code>{text}</code> ({id_type})\n"
        text_msg += f"✅ Мин. цена: <code>{min_price:.2f} {settings_manager.get('currency', 'USD')}</code>\n\n"
        text_msg += "Выберите валюту Steam для отслеживания:"
        
        keyboard = K()
        keyboard.row(
            B("🇺🇦 UAH", callback_data=f"wizard_currency:UAH"),
            B("🇺🇸 USD", callback_data=f"wizard_currency:USD")
        )
        keyboard.row(
            B("🇷🇺 RUB", callback_data=f"wizard_currency:RUB"),
            B("🇰🇿 KZT", callback_data=f"wizard_currency:KZT")
        )
        keyboard.add(B("🇪🇺 EUR", callback_data=f"wizard_currency:EUR"))
        keyboard.add(B("◀ К лотам", callback_data=f"{CallbackButtons.LOTS_MENU}:0"))
        
        bot.send_message(message.chat.id, text_msg, reply_markup=keyboard, parse_mode="HTML")
        return True
    
    def _handle_max_price(self, message, bot, user_key: str, text: str) -> bool:
        """Обрабатывает ввод максимальной цены"""
        state_data = self.wizard_states[user_key]
        lot_id = state_data.get("lot_id")
        steam_id = state_data.get("steam_id")
        steam_currency = state_data.get("steam_currency")
        min_price = state_data.get("min_price")
        
        try:
            max_price = float(text.replace(",", "."))
            if max_price <= min_price:
                bot.reply_to(message, f"❌ Максимальная цена должна быть больше {min_price:.2f}")
                return True
        except ValueError:
            bot.reply_to(message, "❌ Введите корректную цену (например: 100.50)")
            return True
        
        # Создаем лот
        success = lot_manager.add_lot(lot_id, steam_id, steam_currency, min_price, max_price)
        
        # Очищаем состояние мастера
        if user_key in self.wizard_states:
            del self.wizard_states[user_key]
            self.save_wizard_states()
        
        if success:
            # Успешное создание
            global_interval_hours = settings_manager.get("time", 21600) // 3600
            
            text_msg = "✅ <b>Лот успешно добавлен!</b>\n\n"
            text_msg += f"📦 ID лота: <code>{lot_id}</code>\n"
            text_msg += f"🎮 Steam ID: <code>{steam_id}</code>\n"
            text_msg += f"💰 Диапазон цен: {min_price:.2f} - {max_price:.2f} {settings_manager.get('currency', 'USD')}\n"
            text_msg += f"🌍 Валюта Steam: {steam_currency}\n\n"
            text_msg += f"⏰ Лот будет автоматически обновляться каждые <b>{global_interval_hours} ч</b>"
            
            keyboard = K()
            keyboard.add(B("📦 К лотам", callback_data=f"{CallbackButtons.LOTS_MENU}:0"))
            keyboard.add(B("🔄 Обновить сейчас", callback_data=f"update_single_lot:{lot_id}"))
            
            bot.send_message(message.chat.id, text_msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            bot.reply_to(message, "❌ Ошибка создания лота")
        
        return True
    
    def handle_currency_selection(self, call: telebot.types.CallbackQuery, bot) -> None:
        """Обрабатывает выбор валюты в мастере"""
        try:
            logger.info(f"{LOGGER_PREFIX} Обработка выбора валюты: call.data = {call.data}")
            
            if not call.data:
                logger.error(f"{LOGGER_PREFIX} Отсутствуют данные callback")
                bot.answer_callback_query(call.id, "❌ Ошибка данных")
                return
            
            # Парсим валюту из callback данных
            callback_parts = call.data.split(':')
            if len(callback_parts) < 2:
                logger.error(f"{LOGGER_PREFIX} Неверный формат callback данных: {call.data}")
                bot.answer_callback_query(call.id, "❌ Ошибка формата данных")
                return
                
            currency = callback_parts[1]
            user_key = self.get_user_key(call)
            
            logger.info(f"{LOGGER_PREFIX} Пользователь {user_key} выбрал валюту: {currency}")
            
            if user_key not in self.wizard_states:
                logger.warning(f"{LOGGER_PREFIX} Состояние мастера не найдено для пользователя {user_key}")
                bot.answer_callback_query(call.id, "❌ Сессия истекла")
                return
            
            state_data = self.wizard_states[user_key]
            logger.debug(f"{LOGGER_PREFIX} Текущее состояние: {state_data}")
            
            lot_id = state_data.get("lot_id")
            steam_id = state_data.get("steam_id")
            min_price = state_data.get("min_price")
            
            if not all([lot_id, steam_id, min_price is not None]):
                logger.error(f"{LOGGER_PREFIX} Отсутствуют необходимые данные: lot_id={lot_id}, steam_id={steam_id}, min_price={min_price}")
                bot.answer_callback_query(call.id, "❌ Ошибка данных")
                return
            
            # Обновляем состояние
            self.wizard_states[user_key] = {
                "step": "max_price",
                "lot_id": lot_id,
                "steam_id": steam_id,
                "steam_currency": currency,
                "min_price": min_price
            }
            self.save_wizard_states()
            
            logger.info(f"{LOGGER_PREFIX} Состояние мастера обновлено на шаг max_price")
            
            text = "🧙‍♂️ <b>Мастер добавления лота</b>\n\n"
            text += "📋 <b>Шаг 4 из 4: Максимальная цена</b>\n\n"
            text += f"✅ ID лота: <code>{lot_id}</code>\n"
            text += f"✅ Steam ID: <code>{steam_id}</code>\n"
            text += f"✅ Валюта: <code>{currency}</code>\n"
            text += f"✅ Мин. цена: <code>{min_price:.2f} {settings_manager.get('currency', 'USD')}</code>\n\n"
            text += f"Введите максимальную цену (больше {min_price:.2f}):"
            
            keyboard = K()
            keyboard.add(B("◀ К лотам", callback_data=f"{CallbackButtons.LOTS_MENU}:0"))
            
            bot.edit_message_text(text, call.message.chat.id, call.message.id,
                                  reply_markup=keyboard, parse_mode="HTML")
            bot.answer_callback_query(call.id, f"✅ Валюта: {currency}")
            
            logger.info(f"{LOGGER_PREFIX} Сообщение о выборе валюты отправлено успешно")
            
        except Exception as e:
            logger.error(f"{LOGGER_PREFIX} Ошибка выбора валюты в мастере: {e}", exc_info=True)
            try:
                bot.answer_callback_query(call.id, "❌ Ошибка")
            except:
                pass

# Глобальный экземпляр мастера
lot_wizard = LotWizard()