import asyncio
from enum import Enum
from typing import Dict, List, Set, Optional
import os
import random
import string
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from logger_config import setup_logging, log_user_action, log_system_event, log_error, log_chat_event

# Загрузка токена из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Инициализация системы логирования
logger = setup_logging()

# --- HTTP endpoint для healthcheck ---
async def healthcheck(request):
    return web.Response(text="OK", status=200)

async def start_http_server():
    app = web.Application()
    app.router.add_get('/health', healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8080)
    await site.start()
    logger.info("HTTP server started on http://localhost:8080")

# --- Состояния пользователя ---
class UserState(Enum):
    IDLE = 'idle'         # только зашёл
    FILLING_POLL = 'filling_poll'  # заполняет опросник
    SEARCHING = 'searching'  # ждёт собеседника
    CHATTING = 'chatting'    # общается с кем-то
    RATING = 'rating'        # оценивает собеседника

# --- In-memory хранилище ---
waiting_queue: List[int] = []  # user_id
active_chats: Dict[int, int] = {}  # user_id: partner_id
user_states: Dict[int, UserState] = {}  # user_id: state
banned_users: Set[int] = set()  # на будущее
chat_timers: Dict[int, asyncio.Task] = {}  # user_id: timer_task

# --- Анкеты пользователей ---
user_profiles: Dict[int, Dict[str, str]] = {}  # user_id: {gender, age}

# --- Анонимные имена и рейтинг ---
anonymous_names: Dict[int, str] = {}  # user_id: anonymous_name
blacklist: Dict[int, Dict[int, datetime]] = {}  # user_id: {blocked_user_id: block_until}
user_stats: Dict[int, Dict[str, int]] = {}  # user_id: {chats_count, messages_sent, rating}

# --- Анти-спам ---
message_timestamps: Dict[int, List[datetime]] = {}  # user_id: [timestamps]
SPAM_LIMIT = 5  # сообщений
SPAM_WINDOW = 10  # секунд

def generate_anonymous_name() -> str:
    """Генерирует случайное анонимное имя"""
    adjectives = ["Тайный", "Скрытый", "Неизвестный", "Анонимный", "Загадочный"]
    nouns = ["Собеседник", "Путник", "Странник", "Гость", "Путник"]
    number = random.randint(100, 999)
    return f"{random.choice(adjectives)} {random.choice(nouns)}-{number}"

def get_user_anonymous_name(user_id: int) -> str:
    """Получает или создает анонимное имя для пользователя"""
    if user_id not in anonymous_names:
        anonymous_names[user_id] = generate_anonymous_name()
    return anonymous_names[user_id]

def is_user_blocked(user_id: int, partner_id: int) -> bool:
    """Проверяет, заблокирован ли один пользователь другим"""
    if user_id in blacklist and partner_id in blacklist[user_id]:
        block_until = blacklist[user_id][partner_id]
        if datetime.now() < block_until:
            return True
        else:
            # Удаляем истекшую блокировку
            del blacklist[user_id][partner_id]
    return False

def add_to_blacklist(user_id: int, blocked_user_id: int):
    """Добавляет пользователя в чёрный список на 10 дней"""
    if user_id not in blacklist:
        blacklist[user_id] = {}
    blacklist[user_id][blocked_user_id] = datetime.now() + timedelta(days=10)
    log_user_action(user_id, f"Blocked user {blocked_user_id} for 10 days")

def check_spam(user_id: int) -> bool:
    """Проверяет, не спамит ли пользователь"""
    now = datetime.now()
    if user_id not in message_timestamps:
        message_timestamps[user_id] = []
    
    # Удаляем старые метки времени
    message_timestamps[user_id] = [
        ts for ts in message_timestamps[user_id] 
        if (now - ts).seconds < SPAM_WINDOW
    ]
    
    # Проверяем лимит
    if len(message_timestamps[user_id]) >= SPAM_LIMIT:
        return True
    
    # Добавляем новую метку времени
    message_timestamps[user_id].append(now)
    return False

def update_user_stats(user_id: int, stat_type: str, value: int = 1):
    """Обновляет статистику пользователя"""
    if user_id not in user_stats:
        user_stats[user_id] = {"chats_count": 0, "messages_sent": 0, "rating": 0}
    user_stats[user_id][stat_type] += value

# --- Клавиатуры ---
def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🟢 Найти собеседника")
    kb.button(text="📊 Моя статистика")
    kb.button(text="ℹ️ Помощь")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def gender_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="👨 Мужской")
    kb.button(text="👩 Женский")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def age_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔞 До 18")
    kb.button(text="✅ 18+")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def chat_menu_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔚 Завершить чат")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

def rating_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="👍 Хорошо")
    kb.button(text="👎 Плохо")
    kb.button(text="😐 Нейтрально")
    kb.adjust(3)
    return kb.as_markup(resize_keyboard=True)

def stats_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="📊 Моя статистика")
    kb.button(text="🟢 Найти собеседника")
    kb.button(text="ℹ️ Помощь")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

# --- Функция автоматического завершения чата ---
async def auto_end_chat(user_id: int, partner_id: int):
    await asyncio.sleep(1800)  # 30 минут = 1800 секунд
    # Проверяем, что чат всё ещё активен
    if (user_id in active_chats and active_chats[user_id] == partner_id and 
        partner_id in active_chats and active_chats[partner_id] == user_id):
        # Удаляем пару
        active_chats.pop(user_id, None)
        active_chats.pop(partner_id, None)
        # Обновляем состояния
        user_states[user_id] = UserState.IDLE
        user_states[partner_id] = UserState.IDLE
        # Удаляем таймеры
        chat_timers.pop(user_id, None)
        chat_timers.pop(partner_id, None)
        log_chat_event(user_id, partner_id, "Auto-ended after 30 minutes")
        # Уведомляем обоих
        try:
            await bot.send_message(user_id, "Чат автоматически завершён через 30 минут. Можешь найти нового собеседника!", reply_markup=main_menu_kb())
        except Exception as e:
            log_error("Failed to notify user about auto-end", f"User {user_id}, Error: {e}")
        try:
            await bot.send_message(partner_id, "Чат автоматически завершён через 30 минут. Можешь найти нового собеседника!", reply_markup=main_menu_kb())
        except Exception as e:
            log_error("Failed to notify partner about auto-end", f"Partner {partner_id}, Error: {e}")

# --- Инициализация бота ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Заготовки для хендлеров ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    log_user_action(user_id, "Started bot")
    # Сброс состояния пользователя
    user_states[user_id] = UserState.IDLE
    # Удаляем из очереди, если вдруг был
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
        log_user_action(user_id, "Removed from waiting queue")
    # Завершаем чат, если был активен
    if user_id in active_chats:
        partner_id = active_chats.pop(user_id)
        # Удаляем обратную связь
        active_chats.pop(partner_id, None)
        log_chat_event(user_id, partner_id, "Chat ended via /start")
        # Уведомляем партнёра, если он есть
        try:
            await bot.send_message(partner_id, "Собеседник покинул чат.", reply_markup=main_menu_kb())
            user_states[partner_id] = UserState.IDLE
        except Exception as e:
            log_error("Failed to notify partner", f"Partner {partner_id}, Error: {e}")
    # Очищаем анкету
    user_profiles.pop(user_id, None)
    # Начинаем опросник
    user_states[user_id] = UserState.FILLING_POLL
    log_user_action(user_id, "Started filling poll")
    text = (
        "Привет! Здесь ты можешь пообщаться анонимно один на один.\n\n"
        "Сначала заполни небольшую анкету для лучшего подбора собеседника.\n"
        "Выбери свой пол:"
    )
    await message.answer(text, reply_markup=gender_kb())

@dp.message(F.text.in_(["👨 Мужской", "👩 Женский"]))
async def handle_gender(message: Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != UserState.FILLING_POLL:
        return
    # Сохраняем пол
    gender = "male" if message.text == "👨 Мужской" else "female"
    user_profiles[user_id] = {"gender": gender}
    # Запрашиваем возраст
    await message.answer("Выбери свой возраст:", reply_markup=age_kb())

@dp.message(F.text.in_(["🔞 До 18", "✅ 18+"]))
async def handle_age(message: Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != UserState.FILLING_POLL:
        return
    # Сохраняем возраст
    age = "under_18" if message.text == "🔞 До 18" else "18_plus"
    if user_id in user_profiles:
        user_profiles[user_id]["age"] = age
    else:
        user_profiles[user_id] = {"age": age}
    # Завершаем опросник
    user_states[user_id] = UserState.IDLE
    text = (
        "Анкета заполнена! Теперь можешь найти собеседника.\n"
        "Нажми 'Найти собеседника', чтобы начать."
    )
    await message.answer(text, reply_markup=main_menu_kb())

@dp.message(F.text == "🟢 Найти собеседника")
async def find_partner(message: Message):
    user_id = message.from_user.id
    log_user_action(user_id, "Searching for partner")
    # Проверяем, заполнена ли анкета
    if user_id not in user_profiles or len(user_profiles[user_id]) < 2:
        log_error("User tried to search without completing poll", f"User {user_id}")
        await message.answer("Сначала заполни анкету! Нажми /start", reply_markup=main_menu_kb())
        return
    # Если пользователь уже в чате — не даём искать
    if user_states.get(user_id) == UserState.CHATTING:
        log_user_action(user_id, "Already in chat")
        await message.answer("Вы уже в чате!", reply_markup=chat_menu_kb())
        return
    # Если пользователь уже ищет — не даём искать повторно
    if user_states.get(user_id) == UserState.SEARCHING:
        log_user_action(user_id, "Already searching")
        await message.answer("Вы уже в поиске собеседника...", reply_markup=main_menu_kb())
        return
    
    my_profile = user_profiles[user_id]
    partner_id = None
    
    # Ищем подходящего собеседника с учетом чёрного списка
    for uid in waiting_queue:
        if uid == user_id:
            continue
        # Проверяем чёрный список
        if is_user_blocked(user_id, uid) or is_user_blocked(uid, user_id):
            continue
        # Проверяем анкету собеседника
        partner_profile = user_profiles.get(uid)
        if not partner_profile:
            continue
        # Фильтрация: совпадение по полу и возрасту
        if (partner_profile["gender"] == my_profile["gender"] and 
            partner_profile["age"] == my_profile["age"]):
            partner_id = uid
            break
    
    if partner_id:
        # Удаляем обоих из очереди
        waiting_queue.remove(partner_id)
        # Обновляем состояния
        user_states[user_id] = UserState.CHATTING
        user_states[partner_id] = UserState.CHATTING
        # Записываем пару
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        # Запускаем таймеры автоматического завершения
        chat_timers[user_id] = asyncio.create_task(auto_end_chat(user_id, partner_id))
        chat_timers[partner_id] = asyncio.create_task(auto_end_chat(partner_id, user_id))
        # Обновляем статистику
        update_user_stats(user_id, "chats_count")
        update_user_stats(partner_id, "chats_count")
        log_chat_event(user_id, partner_id, "Chat started")
        # Оповещаем обоих
        await message.answer("Собеседник найден! Можете начинать общение.", reply_markup=chat_menu_kb())
        try:
            await bot.send_message(partner_id, "Собеседник найден! Можете начинать общение.", reply_markup=chat_menu_kb())
        except Exception as e:
            log_error("Failed to notify partner", f"Partner {partner_id}, Error: {e}")
    else:
        # Добавляем в очередь
        waiting_queue.append(user_id)
        user_states[user_id] = UserState.SEARCHING
        log_user_action(user_id, f"Added to waiting queue (total: {len(waiting_queue)})")
        await message.answer("Ожидание собеседника...", reply_markup=main_menu_kb())

@dp.message(F.text == "🔚 Завершить чат")
async def end_chat(message: Message):
    user_id = message.from_user.id
    log_user_action(user_id, "Manually ended chat")
    if user_states.get(user_id) != UserState.CHATTING:
        await message.answer("Вы не находитесь в чате.", reply_markup=main_menu_kb())
        return
    # Получаем партнёра
    partner_id = active_chats.pop(user_id, None)
    if partner_id:
        active_chats.pop(partner_id, None)
        user_states[partner_id] = UserState.IDLE
        # Отменяем таймеры
        if user_id in chat_timers:
            chat_timers[user_id].cancel()
            chat_timers.pop(user_id)
        if partner_id in chat_timers:
            chat_timers[partner_id].cancel()
            chat_timers.pop(partner_id)
        log_chat_event(user_id, partner_id, "Manually ended")
        # Предлагаем оценить собеседника
        user_states[user_id] = UserState.RATING
        await message.answer(
            f"Как вам общение с {get_user_anonymous_name(partner_id)}?",
            reply_markup=rating_kb()
        )
        try:
            await bot.send_message(partner_id, "Чат завершён. Можешь найти нового собеседника!", reply_markup=main_menu_kb())
        except Exception as e:
            log_error("Failed to notify partner", f"Partner {partner_id}, Error: {e}")
    else:
        user_states[user_id] = UserState.IDLE
        await message.answer("Чат завершён. Можешь найти нового собеседника!", reply_markup=main_menu_kb())

@dp.message(F.text == "ℹ️ Помощь")
async def help_message(message: Message):
    text = (
        "🔒 Анонимный чат 1-на-1\n\n"
        "• Ваши личные данные и ID не раскрываются.\n"
        "• Все сообщения пересылаются ботом вручную.\n"
        "• Можно завершить чат в любой момент.\n"
        "• Доступен только текст (медиа — позже).\n\n"
        "Нажмите 'Найти собеседника', чтобы начать!"
    )
    await message.answer(text, reply_markup=main_menu_kb())

@dp.message(F.text.in_(["👍 Хорошо", "👎 Плохо", "😐 Нейтрально"]))
async def handle_rating(message: Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != UserState.RATING:
        return
    
    # Получаем последнего собеседника (временно храним в состоянии)
    partner_id = None
    for uid, partner in active_chats.items():
        if partner == user_id:
            partner_id = uid
            break
    
    if not partner_id:
        # Ищем в обратной связи
        for uid, partner in active_chats.items():
            if uid == user_id:
                partner_id = partner
                break
    
    rating_value = 0
    if message.text == "👍 Хорошо":
        rating_value = 1
        log_user_action(user_id, f"Rated partner {partner_id} as Good")
    elif message.text == "👎 Плохо":
        rating_value = -1
        # Добавляем в чёрный список
        if partner_id:
            add_to_blacklist(user_id, partner_id)
            log_user_action(user_id, f"Rated partner {partner_id} as Bad (blocked)")
    else:  # Нейтрально
        log_user_action(user_id, f"Rated partner {partner_id} as Neutral")
    
    if partner_id:
        update_user_stats(partner_id, "rating", rating_value)
    
    user_states[user_id] = UserState.IDLE
    await message.answer("Спасибо за оценку! Можешь найти нового собеседника.", reply_markup=main_menu_kb())

@dp.message(F.text == "📊 Моя статистика")
async def show_stats(message: Message):
    user_id = message.from_user.id
    stats = user_stats.get(user_id, {"chats_count": 0, "messages_sent": 0, "rating": 0})
    log_user_action(user_id, "Viewed statistics")
    
    text = (
        f"📊 **Твоя статистика:**\n\n"
        f"💬 Чатов: {stats['chats_count']}\n"
        f"📝 Сообщений отправлено: {stats['messages_sent']}\n"
        f"⭐ Рейтинг: {stats['rating']}\n"
        f"🆔 Твой ник: {get_user_anonymous_name(user_id)}"
    )
    
    await message.answer(text, reply_markup=main_menu_kb())

# --- Пересылка сообщений между собеседниками ---
@dp.message()
async def relay_message(message: Message):
    user_id = message.from_user.id
    
    # Проверяем спам
    if check_spam(user_id):
        await message.answer("Слишком много сообщений! Подожди немного.", reply_markup=chat_menu_kb())
        return
    
    if user_states.get(user_id) == UserState.CHATTING:
        partner_id = active_chats.get(user_id)
        if not partner_id:
            return
        
        # Обновляем статистику сообщений
        update_user_stats(user_id, "messages_sent")
        
        # Текст
        if message.text:
            await bot.send_message(partner_id, message.text)
        # Фото
        elif message.photo:
            await bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
        # Документ
        elif message.document:
            await bot.send_document(partner_id, message.document.file_id, caption=message.caption)
        # Голосовое
        elif message.voice:
            await bot.send_voice(partner_id, message.voice.file_id)
        # Стикер
        elif message.sticker:
            await bot.send_sticker(partner_id, message.sticker.file_id)
        # Видео
        elif message.video:
            await bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        # Аудио
        elif message.audio:
            await bot.send_audio(partner_id, message.audio.file_id, caption=message.caption)
        # Контакт
        elif message.contact:
            await bot.send_contact(partner_id, message.contact.phone_number, message.contact.first_name)
        # Геолокация
        elif message.location:
            await bot.send_location(partner_id, message.location.latitude, message.location.longitude)
        # Место (venue)
        elif message.venue:
            await bot.send_venue(partner_id, message.venue.location.latitude, message.venue.location.longitude, 
                               message.venue.title, message.venue.address)
        # Анимация (GIF)
        elif message.animation:
            await bot.send_animation(partner_id, message.animation.file_id, caption=message.caption)
        # Видео-заметка
        elif message.video_note:
            await bot.send_video_note(partner_id, message.video_note.file_id)
        # Если тип не поддержан
        else:
            await bot.send_message(user_id, "Этот тип сообщения пока не поддерживается.")
    elif user_states.get(user_id) == UserState.SEARCHING:
        await message.answer("Ожидание собеседника...", reply_markup=main_menu_kb())
    elif user_states.get(user_id) == UserState.FILLING_POLL:
        await message.answer("Сначала заверши заполнение анкеты!", reply_markup=gender_kb())
    elif user_states.get(user_id) == UserState.RATING:
        await message.answer("Сначала оцени собеседника!", reply_markup=rating_kb())
    else:
        await message.answer("Нажмите 'Найти собеседника', чтобы начать чат.", reply_markup=main_menu_kb())

async def main():
    log_system_event("Starting bot")
    # Запускаем HTTP сервер в фоне
    http_task = asyncio.create_task(start_http_server())
    # Запускаем админ-панель в фоне
    from admin_panel import start_admin_server
    admin_task = asyncio.create_task(start_admin_server())
    # Запускаем бота
    await dp.start_polling(bot)
    # Останавливаем HTTP сервер при завершении бота
    http_task.cancel()
    admin_task.cancel()

if __name__ == "__main__":
    asyncio.run(main()) 