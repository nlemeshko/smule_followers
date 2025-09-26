#!/usr/bin/env python3
"""
Простой healthcheck скрипт для Python приложения
Проверяет, что Python интерпретатор работает и основные модули доступны
"""

import sys
import os

def main():
    try:
        # Проверяем, что Python работает
        if sys.version_info < (3, 6):
            print("ERROR: Python version too old")
            sys.exit(1)
        
        # Проверяем основные модули
        required_modules = [
            'asyncio',
            'aiohttp', 
            'telegram',
            'json',
            'os',
            'ssl',
            'logging'
        ]
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError as e:
                print(f"ERROR: Module {module} not available: {e}")
                sys.exit(1)
        
        # Проверяем переменные окружения
        required_env_vars = ['TELEGRAM_TOKEN', 'CHAT_ID', 'SMULE_ACCOUNT_IDS']
        missing_vars = []
        
        for var in required_env_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            print(f"WARNING: Missing environment variables: {', '.join(missing_vars)}")
            # Не выходим с ошибкой, так как переменные могут быть загружены позже
        
        print("OK: Health check passed")
        sys.exit(0)
        
    except Exception as e:
        print(f"ERROR: Health check failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
