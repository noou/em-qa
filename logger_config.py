import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

def setup_logging():
    """Настройка современной системы логирования с ротацией по дням"""
    
    # Создаём директорию для логов
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Создаём директорию для текущего дня
    today = datetime.now().strftime("%Y-%m-%d")
    daily_logs_dir = logs_dir / today
    daily_logs_dir.mkdir(exist_ok=True)
    
    # Настройка форматирования
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)-15s | %(funcName)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Основной логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Очищаем существующие хендлеры
    logger.handlers.clear()
    
    # 1. Консольный хендлер (с цветами)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. Файл для всех логов
    all_logs_file = daily_logs_dir / "all.log"
    file_handler = logging.FileHandler(all_logs_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 3. Файл только для ошибок
    errors_file = daily_logs_dir / "errors.log"
    error_handler = logging.FileHandler(errors_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    # 4. Файл для действий пользователей
    actions_file = daily_logs_dir / "user_actions.log"
    actions_handler = logging.FileHandler(actions_file, encoding='utf-8')
    actions_handler.setLevel(logging.INFO)
    actions_handler.setFormatter(formatter)
    logger.addHandler(actions_handler)
    
    # Создаём специальный логгер для действий пользователей
    user_logger = logging.getLogger("user_actions")
    user_logger.setLevel(logging.INFO)
    user_logger.handlers.clear()
    user_logger.addHandler(actions_handler)
    user_logger.propagate = False  # Не дублируем в основной лог
    
    # Создаём логгер для системных событий
    system_logger = logging.getLogger("system")
    system_logger.setLevel(logging.INFO)
    
    # Логируем запуск системы
    logger.info("=" * 60)
    logger.info("Система логирования инициализирована")
    logger.info(f"Директория логов: {daily_logs_dir}")
    logger.info(f"Дата: {today}")
    logger.info("=" * 60)
    
    return logger

def get_user_logger():
    """Возвращает логгер для действий пользователей"""
    return logging.getLogger("user_actions")

def get_system_logger():
    """Возвращает логгер для системных событий"""
    return logging.getLogger("system")

def log_user_action(user_id: int, action: str, details: str = ""):
    """Логирует действие пользователя"""
    user_logger = get_user_logger()
    user_logger.info(f"User {user_id} | {action} | {details}")

def log_system_event(event: str, details: str = ""):
    """Логирует системное событие"""
    system_logger = get_system_logger()
    system_logger.info(f"SYSTEM: {event} | {details}")

def log_error(error: str, details: str = ""):
    """Логирует ошибку"""
    logger = logging.getLogger()
    logger.error(f"ERROR: {error} | {details}")

def log_chat_event(user_id: int, partner_id: int, event: str):
    """Логирует событие чата"""
    user_logger = get_user_logger()
    user_logger.info(f"CHAT: User {user_id} <-> {partner_id} | {event}")

def log_admin_action(admin_id: int, action: str, target: str = ""):
    """Логирует действие администратора"""
    system_logger = get_system_logger()
    system_logger.info(f"ADMIN {admin_id} | {action} | {target}") 