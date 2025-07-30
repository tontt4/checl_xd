# Інструкції для об'єднання Steam Price Updater в один файл

## Короткий огляд
Щоб об'єднати весь код у один файл, виконайте наступні кроки:

1. Створіть новий файл steam_price_updater_single.py
2. Додайте всі імпорти з усіх файлів на початок
3. Скопіюйте всі класи з файлів у такому порядку:
   - steam_price_updater/core/config.py (Config, SettingsManager, CallbackButtons)
   - steam_price_updater/core/cache.py (UnifiedCache, CacheManager)
   - steam_price_updater/api/currency.py (CurrencyAPI)
   - steam_price_updater/api/steam.py (SteamAPI)
   - steam_price_updater/core/price_calculator.py (PriceCalculator)
   - steam_price_updater/core/lot_manager.py (LotManager)
   - steam_price_updater/core/updater.py (LotUpdater)
   - steam_price_updater/ui/wizard.py (LotWizard)
   - steam_price_updater/ui/telegram_handlers.py (TelegramHandlers)

4. Видаліть всі relative imports (from .. import)
5. Змініть конструктори класів для прийняття залежностей
6. Створіть глобальні екземпляри в кінці файлу
7. Додайте функції init, post_start, cleanup_resources
8. Додайте BIND_TO_ константи

Весь код буде працювати в одному файлі без модульної структури.
