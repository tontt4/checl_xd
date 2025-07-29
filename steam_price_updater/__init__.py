"""
Steam Price Updater Plugin - рефакторована версія

Автоматическое обновление цен лотов на основе Steam API с выбором валют
Версия: 2.1.0
Автор: @humblegodq
"""

# Основные константы плагина
NAME = "Steam Price Updater"
VERSION = "2.1.0"
DESCRIPTION = "Автоматическое обновление цен лотов на основе Steam API с выбором валют"
CREDITS = "@humblegodq"
UUID = "247153d9-f732-4f01-a11f-a3945b68b533"
SETTINGS_PAGE = True

__version__ = VERSION
__author__ = CREDITS
__description__ = DESCRIPTION

__all__ = [
    'NAME', 'VERSION', 'DESCRIPTION', 'CREDITS', 'UUID', 'SETTINGS_PAGE'
]